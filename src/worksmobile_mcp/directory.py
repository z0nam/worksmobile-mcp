"""Directory (members) helpers — read-only by design.

No write verbs live here. Account creation/suspension/transfers belong in the
WORKS admin console: they are hard to reverse and carry legal weight. This module
audits and reconciles instead.
"""
from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone

from .core import ApiError, call, token_for

PAGE = 100  # /users returns an empty page for count > 100 (observed 2026-08-07)


def users_all(user: str | None = None, include_deleted: bool = False) -> list:
    """Fetch every member of the tenant."""
    token = token_for(user, scope="user.read")
    out, cursor = [], None
    while True:
        params = {"count": PAGE}
        if cursor:
            params["cursor"] = cursor
        st, r = call("GET", "/users", token, params=params)
        if st != 200:
            raise ApiError(st, r)
        out += r.get("users", [])
        cursor = r.get("responseMetaData", {}).get("nextCursor")
        if not cursor:
            break
    if not include_deleted:
        out = [u for u in out if not u.get("isDeleted")]
    return out


def _orgunits(u):
    for org in u.get("organizations") or []:
        for ou in org.get("orgUnits") or []:
            yield ou


def flat(u: dict) -> dict:
    """Flatten a user object down to the fields worth auditing."""
    ous = list(_orgunits(u))
    primary = next((o for o in ous if o.get("primary")), ous[0] if ous else {})
    loa = u.get("leaveOfAbsence") or {}
    name = u.get("userName")
    if isinstance(name, dict):
        name = (name.get("lastName") or "") + (name.get("firstName") or "")
    return {
        "email": u.get("email"),
        "name": name or "",
        # dept = primary org unit; depts keeps them all (joint appointments are common)
        "dept": primary.get("orgUnitName") or "",
        "depts": [o.get("orgUnitName") or "" for o in ous],
        "position": primary.get("positionName") or "",
        "isManager": bool(primary.get("isManager")),
        "employeeNumber": u.get("employeeNumber") or "",
        "hiredDate": u.get("hiredDate") or "",
        "aliases": u.get("aliasEmails") or [],
        "isAdministrator": bool(u.get("isAdministrator")),
        "isSuspended": bool(u.get("isSuspended")),
        "isDeleted": bool(u.get("isDeleted")),
        "isPending": bool(u.get("isPending")),
        "isAwaiting": bool(u.get("isAwaiting")),
        "onLeave": bool(loa.get("isLeaveOfAbsence")),
        "userId": u.get("userId"),
        "deptCount": len(ous),
    }


def _age_days(ts):
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            d = datetime.strptime(ts, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - d).days
        except ValueError:
            continue
    return None


# (code, severity, description, predicate)
RULES = [
    ("LEAVE_ACTIVE", "high",
     "On leave but the account is not suspended — mail and drive access are still live",
     lambda f: f["onLeave"] and not f["isSuspended"]),
    ("NO_DEPT", "medium",
     "No org unit assigned — invisible to org-based sharing, or a leftover account",
     lambda f: f["deptCount"] == 0 and not f["isSuspended"]),
    ("PENDING_STALE", "medium",
     "Pending/awaiting activation for more than 30 days",
     lambda f: (f["isPending"] or f["isAwaiting"]) and (_age_days(f["hiredDate"]) or 0) > 30),
    ("SUPER_ADMIN", "info",
     "Holds super-administrator rights — review periodically",
     lambda f: f["isAdministrator"]),
]

# Questions the API cannot answer at all. Always reported alongside findings so an
# empty result is never mistaken for full coverage.
BLIND_SPOTS = [
    {"area": "delegated (sub-)administrators",
     "note": "`isAdministrator` is true only for SUPER admins. Sub-administrators holding "
             "a permission group are not exposed anywhere in the API (observed 2026-08-11: "
             "an account that is a sub-admin in the console still reports false). "
             "Enumerate admin rights in the WORKS admin console instead."},
]

# Field each rule depends on. If the tenant leaves it empty, that rule is DORMANT —
# reporting "no findings" would be a lie, so callers must surface this.
RULE_FIELDS = {"LEAVE_ACTIVE": "onLeave", "PENDING_STALE": "hiredDate",
               "NO_DEPT": None, "SUPER_ADMIN": None}


def coverage(users: list) -> dict:
    """How many members actually have each audited field populated."""
    rows = [flat(u) for u in users]
    fields = ("dept", "position", "hiredDate", "employeeNumber", "onLeave", "isSuspended")
    return {"total": len(rows), **{f: sum(1 for r in rows if r.get(f)) for f in fields}}


def dormant_rules(users: list) -> list:
    """Rules that cannot fire because their source field is empty tenant-wide."""
    cov = coverage(users)
    return [c for c, f in RULE_FIELDS.items() if f and not cov.get(f)]


def findings(users: list, ignore=()) -> list:
    """Rule-based audit. `ignore` = emails to skip (shared/functional accounts)."""
    ign = {e.strip().lower() for e in ignore if e and e.strip()}
    out = []
    for u in users:
        f = flat(u)
        if (f["email"] or "").lower() in ign:
            continue
        for code, sev, desc, test in RULES:
            try:
                hit = test(f)
            except Exception:
                hit = False
            if hit:
                out.append({"code": code, "severity": sev, "desc": desc,
                            "email": f["email"], "name": f["name"], "dept": f["dept"]})
    order = {"high": 0, "medium": 1, "info": 2}
    out.sort(key=lambda x: (order.get(x["severity"], 9), x["code"], x["email"] or ""))
    return out


def load_roster(path: str) -> dict:
    """Load an external roster (CSV/TSV) -> {lowercased email: row}. Email column auto-detected."""
    with open(path, newline="", encoding="utf-8") as fh:
        first = fh.readline()
        fh.seek(0)
        rows = list(csv.DictReader(fh, delimiter="\t" if "\t" in first else ","))
    if not rows:
        return {}
    email_col = next((c for c in rows[0] if c and "mail" in c.lower()), None)
    if not email_col:
        raise RuntimeError(f"{path}: no email column found (header: {list(rows[0])})")
    return {(r.get(email_col) or "").strip().lower(): r
            for r in rows if (r.get(email_col) or "").strip()}


def own_domains(users: list, extra: str | None = None) -> set:
    """Domains we own: every domain seen on a WORKS account, plus `extra` (comma-separated)."""
    doms = {(flat(u)["email"] or "").split("@")[-1].lower() for u in users if flat(u)["email"]}
    doms |= {d.strip().lower().lstrip("@") for d in (extra or "").split(",") if d.strip()}
    return {d for d in doms if d}


def drift(users: list, roster: dict, name_col: str | None = None,
          ignore=(), domain: str | None = None) -> dict:
    """Reconcile WORKS accounts against an external roster.

    only_works : in WORKS but not in the roster -> suspected leftover (ex-employee)
    only_roster: in the roster but has no WORKS account, **own domains only**
    external   : roster entries on other domains (partner org staff, not our concern)
    """
    ign = {e.strip().lower() for e in ignore if e and e.strip()}
    wm = {}
    for u in users:
        f = flat(u)
        if f["email"] and f["email"].lower() not in ign:
            wm[f["email"].lower()] = f
    doms = own_domains(users, domain)
    missing = [e for e in sorted(set(roster) - set(wm)) if e not in ign]
    mine = [e for e in missing if e.split("@")[-1].lower() in doms]
    return {
        "domains": sorted(doms),
        "matched": len(set(wm) & set(roster)),
        "only_works": [wm[e] for e in sorted(set(wm) - set(roster))],
        "only_roster": [{"email": e, **roster[e]} for e in mine],
        "external": [{"email": e, **roster[e]} for e in missing if e not in set(mine)],
        "name_diff": [
            {"email": e, "works": wm[e]["name"].strip(), "roster": (roster[e].get(name_col) or "").strip()}
            for e in sorted(set(wm) & set(roster))
            if name_col and (wm[e]["name"] or "").strip()
            and (roster[e].get(name_col) or "").strip()
            and wm[e]["name"].strip() != (roster[e].get(name_col) or "").strip()
        ] if name_col else [],
    }


def domain_counts(users: list) -> dict:
    return dict(Counter((flat(u)["email"] or "").split("@")[-1].lower()
                        for u in users if flat(u)["email"]))


def member_footprint(email: str, admin_user: str | None = None,
                     rosters: dict | None = None) -> dict:
    """Everything this API can tell you about one member's reach.

    The reference query for offboarding and transfers. `rosters` maps a label to
    {"path": ..., "key": "email"|"name"} for external cross-checks.

    Order matters operationally: run this BEFORE suspending the account. Once the
    account is suspended, delegation to it fails and the My Drive / received-folder
    sections below become unavailable.
    """
    from . import core
    users = users_all(admin_user, include_deleted=True)
    me = next((u for u in users if (flat(u)["email"] or "").lower() == email.lower()), None)
    if not me:
        raise RuntimeError(f"no WORKS account for {email}")
    f = flat(me)

    roster_hits = {}
    for label, cfg in (rosters or {}).items():
        try:
            r = load_roster(cfg["path"], key=cfg.get("key", "email"))
            probe = f["name"].strip() if cfg.get("key") == "name" else email.lower()
            roster_hits[label] = probe in r
        except Exception as e:
            roster_hits[label] = f"error: {e}"

    ftok = core.token_for(admin_user, scope="file")
    st, r = core.call("GET", "/sharedrives", ftok)
    drives = (r if isinstance(r, list) else r.get("sharedrives", [])) if st == 200 else []
    master_of, granted, open_to_all = [], [], []
    for d in drives:
        sd, nm = d.get("sharedriveId"), d.get("name", "")
        # Masters do NOT appear in /permissions — they live on the drive object.
        if any(m.get("id") in (email, f["userId"]) for m in (d.get("masters") or [])):
            master_of.append({"name": nm, "sharedriveId": sd})
        if d.get("accessibleRange") in ("DOMAIN", "TENANT"):
            open_to_all.append({"name": nm, "range": d.get("accessibleRange"),
                                "permissionType": d.get("permissionType")})
            continue
        _, pr = core.call("GET", f"/sharedrives/{sd}/permissions", ftok)
        for p in (pr.get("permissions", []) if isinstance(pr, dict) else []):
            if p.get("userId") in (email, f["userId"]) or p.get("email") == email:
                granted.append({"name": nm, "sharedriveId": sd, "type": p.get("type"),
                                "permissionId": p.get("permissionId")})

    own = {"available": True}
    try:
        utok = core.token_for(email, scope="file")
        items, cursor = [], None
        while True:
            params = {"count": 200}
            if cursor:
                params["cursor"] = cursor
            _, rr = core.call("GET", "/users/me/drive/files", utok, params=params)
            items += (rr or {}).get("files", [])
            cursor = (rr or {}).get("responseMetaData", {}).get("nextCursor")
            if not cursor:
                break
        _, sf = core.call("GET", "/users/me/drive/sharedfolders", utok)
        own = {"available": True, "root_items": len(items),
               "shared_out": [{"fileName": x["fileName"], "fileId": x["fileId"]}
                              for x in items if x.get("shared")],
               "received": (sf or {}).get("sharedFolders", [])}
    except Exception as e:
        own = {"available": False,
               "reason": f"{e}",
               "hint": "If the account is already suspended/deleted, delegation fails. "
                       "This is why the footprint must be collected BEFORE suspension."}

    return {
        "account": f,
        "rosters": roster_hits,
        "drives": {"master_of": master_of, "granted": granted, "open_to_everyone": open_to_all},
        "own_drive": own,
        "blind_spots": BLIND_SPOTS + [
            {"area": "folder-level permissions",
             "note": "There is no reverse index: you cannot ask 'which folders does X have "
                     "permission on'. Check specific folders with the folder permissions tool."},
        ],
    }


def norm_phone(v: str | None) -> str:
    """Normalise a Korean mobile number for joining across sources.

    Stripping `82` alone is NOT enough: many records carry the country code *and* the
    trunk zero (`+82 010-1234-5678`), which naive stripping turns into `00…` — matching
    nothing. Observed on 40% of one tenant's numbers.
    """
    import re
    d = re.sub(r"\D", "", v or "")
    if d.startswith("82"):
        d = d[2:]
    while d.startswith("00"):
        d = d[1:]
    if d and not d.startswith("0"):
        d = "0" + d
    return d


def _index_roster(path: str) -> dict:
    """Index one roster file by every key it offers: email, phone, name."""
    import csv as _csv, json as _json, pathlib as _pl
    pth = _pl.Path(path).expanduser()
    if pth.suffix == ".json":
        d = _json.loads(pth.read_text(encoding="utf-8"))
        rows = d if isinstance(d, list) else (d.get("contacts") or d.get("people") or [])
    else:
        with open(pth, newline="", encoding="utf-8") as fh:
            first = fh.readline(); fh.seek(0)
            rows = list(_csv.DictReader(fh, delimiter="\t" if "\t" in first else ","))
    idx = {"email": {}, "phone": {}, "name": {}}
    if not rows:
        return idx
    cols = list(rows[0])
    pick = lambda *t: next((c for c in cols if c and any(x in c.lower() for x in t)), None)
    ec, pc = pick("mail"), pick("mobile", "phone", "tel")
    nc = pick("name", "krnnm", "이름", "성명")
    for r in rows:
        if ec and (r.get(ec) or "").strip():
            idx["email"][r[ec].strip().lower()] = r
        if pc and norm_phone(r.get(pc)):
            idx["phone"][norm_phone(r.get(pc))] = r
        if nc and (r.get(nc) or "").strip():
            idx["name"][r[nc].strip()] = r
    return idx


def corroborate(rows: list, rosters: dict) -> list:
    """Check "missing" accounts against OTHER rosters before calling anyone a leaver.

    Every roster has a population it simply does not cover — an HR register may omit
    visiting researchers entirely, a chat directory cannot hold people with no corporate
    mail. **Absence from one source is a signal, not evidence.** Treating it as evidence
    is how a current employee's account gets deleted; that happened once, which is why
    this exists.

    Each roster is indexed by email, phone AND name, and probed with whatever the account
    actually has — no single key suffices. (Real case: a member had no phone on the account
    and no corporate mail, so only the name matched.)

    `rosters` maps label -> file path. Adds `seen_in` to each row.
    """
    idx = {}
    for label, path in (rosters or {}).items():
        try:
            idx[label] = _index_roster(path)
        except Exception:
            idx[label] = {"email": {}, "phone": {}, "name": {}}
    for r in rows:
        seen = []
        probes = (("email", (r.get("email") or "").lower()),
                  ("phone", norm_phone(r.get("cellPhone"))),
                  ("name", (r.get("name") or "").strip()))
        for label, ix in idx.items():
            for key, val in probes:
                if val and val in ix[key]:
                    seen.append(f"{label}({key})")
                    break
        r["seen_in"] = seen
    return rows
