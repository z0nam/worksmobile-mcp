"""SCIM provisioning client — the only way to change a member's login state.

This is a **different API family** from the Drive/Directory client in `core`. It is not
reached with the service-account JWT: in the Developer Console you create a *Provisioning
app*, enable SCIM, and it issues a **Long-Lived Token** of its own. Set it as
`WORKS_SCIM_TOKEN`.

Why it exists here at all — the Directory API exposes `isSuspended` as **read-only**, so
there is no way to suspend or restore an account with the credential the rest of this
package uses. SCIM has exactly one write we need:

    PATCH /scim/v2/Users/{id}  {"op": "replace", "path": "active", "value": false}

`active: false` blocks login; `active: true` restores it. Data is untouched either way.

**This token cannot permanently delete anyone, and that is the point.** Even SCIM's
`DELETE /Users/{id}` only deactivates and keeps the data. The Directory `user` scope, by
contrast, carries a real `DELETE /users` that erases a member outright. Scoping account
state changes to this credential means the automation *cannot* perform the irreversible
operation, no matter what it is asked to do. Prefer it over adding `user` scope.

Limits, observed:

- Org unit, position, title and visibility **cannot** be set over SCIM — set them in the
  console after creating a member.
- Leave of absence (`leaveOfAbsence`) is not a SCIM attribute either. It is a console-only
  marker and it is **independent of login blocking**: a member can be marked on leave and
  still be able to log in. Do not treat the two as one axis.
- Filters support `eq` only. Rate limit 240 req/min.
- **The token has a 90-day sliding expiry — any call renews it.** The failure mode this
  creates is quiet: automation that only touches SCIM when it has work to do will go
  untouched for 90 days, and then fail at the first moment a real suspension is needed.
  Call `keepalive()` on every scheduled run, including the runs with nothing to do.
- A token is shown once at creation. Lose it and the only path is expiry + reissue.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .core import load_env

BASE = "https://www.worksapis.com/scim/v2"
TOKEN_KEY = "WORKS_SCIM_TOKEN"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"

# App service accounts live in the same member list as people. Suspending the one your
# own automation authenticates as takes the tooling down with it, so refuse by pattern
# rather than trusting the caller to notice.
SERVICE_ACCOUNT_RE = re.compile(r"\.serviceaccount@", re.I)


def token() -> str | None:
    """The Long-Lived Token, or None if unset. Absence is not an error — callers that
    only read should keep working without it."""
    return (load_env().get(TOKEN_KEY) or "").strip() or None


def available() -> bool:
    return token() is not None


def _token_or_die() -> str:
    t = token()
    if not t:
        raise RuntimeError(
            f"{TOKEN_KEY} is not set. The Directory API cannot change account state "
            "(isSuspended is read-only) — create a Provisioning app in the Developer "
            "Console, enable SCIM, and issue a Long-Lived Token.")
    return t


def call(method: str, path: str, tok: str, params: dict | None = None, body=None):
    """Raw SCIM call. Returns (status_code, parsed_body_or_text)."""
    url = BASE + path
    if params:
        url += "?" + urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/scim+json",
    })
    try:
        with urlopen(req) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def keepalive(tok: str | None = None) -> bool:
    """Push the token's 90-day expiry out by one cheap call. Never raises — this is
    insurance, not the job, and a scheduled run should not die because it failed."""
    try:
        st, _ = call("GET", "/Users", tok or _token_or_die(), params={"count": 1})
        return st == 200
    except Exception:
        return False


def find_id(tok: str, email: str, detail: bool = False):
    """Resolve an email to the SCIM `id`. None when it is not exactly one match.

    We do not assume the path parameter equals the Directory API's `userId`
    (`resourceId`) — that is undocumented, so the id is **looked up, never guessed**.

    With `detail=True`, returns `(id, match_count, reason)`. **Zero matches and two
    matches are entirely different situations** and a single None cannot express both:
    zero usually means "nothing to do", while two or more means *the same userName
    exists twice*, which a human needs to look at.
    """
    if '"' in email or "\\" in email:
        # The filter is string-concatenated, and a quote breaks the expression. The
        # escaping rules are not documented, so refuse rather than guess.
        raise RuntimeError(f"email not usable in a SCIM filter: {email!r}")
    st, r = call("GET", "/Users", tok, params={"filter": f'userName eq "{email}"'})
    if st != 200 or not isinstance(r, dict):
        raise RuntimeError(f"SCIM lookup failed {st} {str(r)[:200]}")
    res = r.get("Resources") or []
    sid = res[0].get("id") if len(res) == 1 else None
    if not detail:
        return sid
    why = "" if sid else ("no such account in SCIM" if not res
                          else f"{len(res)} accounts share this userName — needs a human")
    return sid, len(res), why


def get_active(tok: str, scim_id: str) -> bool:
    """Current `active` value. Used to re-read after a write: a 200 on the PATCH does
    not by itself prove the value changed."""
    st, r = call("GET", f"/Users/{scim_id}", tok)
    if st != 200 or not isinstance(r, dict):
        raise RuntimeError(f"SCIM re-read failed {st} {str(r)[:200]}")
    return bool(r.get("active"))


def set_active(tok: str, scim_id: str, active: bool) -> dict:
    """Suspend (False) / restore (True). Data is removed in neither direction."""
    body = {"schemas": [PATCH_SCHEMA],
            "Operations": [{"op": "replace", "path": "active", "value": bool(active)}]}
    st, r = call("PATCH", f"/Users/{scim_id}", tok, body=body)
    if not 200 <= st < 300:
        raise RuntimeError(f"SCIM PATCH active={active} -> {st} {str(r)[:200]}")
    return r


def create_user(tok: str, email: str, family_name: str, given_name: str) -> dict:
    """Add a member. Org unit, position and employee number cannot be set over SCIM —
    assign them in the console afterwards, or the member lands with no org unit."""
    body = {"schemas": [USER_SCHEMA], "userName": email,
            "name": {"familyName": family_name, "givenName": given_name},
            "active": True}
    st, r = call("POST", "/Users", tok, body=body)
    if not 200 <= st < 300:
        raise RuntimeError(f"SCIM POST /Users -> {st} {str(r)[:200]}")
    return r


# ---------- verbs ----------

def user_set_active(email: str, active: bool) -> dict:
    """Suspend or restore one member, then **verify by re-reading**.

    Login state is the kind of thing that must not be reported as done on the strength
    of a 2xx alone: if the value did not actually change, the caller has to hear about
    it rather than be told success.
    """
    email = email.strip()
    if SERVICE_ACCOUNT_RE.search(email):
        raise RuntimeError(
            f"{email} is an app service account — suspending it stops your own tooling. "
            "This verb is for human accounts only.")
    tok = _token_or_die()
    sid, n, why = find_id(tok, email, detail=True)
    if not sid:
        raise RuntimeError(f"cannot identify {email} in SCIM: {why}")
    set_active(tok, sid, active)
    got = get_active(tok, sid)
    want = bool(active)
    if got is not want:
        raise RuntimeError(
            f"the request succeeded but the value did not change — {email} active={got} "
            f"(wanted {want}). Check the admin console.")
    out = {"email": email, "scim_id": sid, "active": got,
           "state": "active" if want else "suspended", "verified": True}
    if not want:
        out["note"] = ("Login is blocked and data is preserved; this is reversible. "
                       "Leave of absence (leaveOfAbsence) is a separate console-only "
                       "marker and was not touched.")
    return out


def user_create(email: str, family_name: str, given_name: str) -> dict:
    """Create a member and say plainly what SCIM could not set."""
    r = create_user(_token_or_die(), email.strip(), family_name, given_name)
    return {"email": email, "scim_id": r.get("id") if isinstance(r, dict) else None,
            "note": ("Created and active. Org unit, position, title and employee number "
                     "are NOT settable over SCIM — assign them in the admin console, "
                     "otherwise the member has no org unit.")}


def status() -> dict:
    """Is the provisioning plane usable at all? For `doctor`."""
    tok = token()
    if not tok:
        return {"configured": False, "usable": False,
                "detail": f"{TOKEN_KEY} not set — account state changes unavailable"}
    st, r = call("GET", "/Users", tok, params={"count": 1})
    if st == 200:
        return {"configured": True, "usable": True,
                "detail": "active/suspend available; this token cannot permanently delete"}
    return {"configured": True, "usable": False, "status": st,
            "detail": (f"token is set but the API answered {st} — it may have hit the "
                       "90-day unused expiry; reissue in the console: "
                       f"{str(r)[:120]}")}
