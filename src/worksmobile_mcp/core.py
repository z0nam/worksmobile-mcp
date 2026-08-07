"""Core NAVER WORKS Drive API client — service-account delegation (JWT).

Config resolution: process env (WORKS_*) > $WORKS_ENV_FILE > ./.env > ~/.config/worksmobile/.env
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import jwt as pyjwt

BASE = "https://www.worksapis.com/v1.0"
TOKEN_URL = "https://auth.worksmobile.com/oauth2/v2.0/token"

ENV_CANDIDATES = [
    os.environ.get("WORKS_ENV_FILE"),
    Path.cwd() / ".env",
    Path.home() / ".config/worksmobile/.env",
]


def load_env() -> dict:
    env: dict = {}
    for cand in ENV_CANDIDATES:
        if not cand:
            continue
        p = Path(cand)
        if not p.is_file():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
        break
    env.update({k: v for k, v in os.environ.items() if k.startswith("WORKS_")})
    return env


def get_token(scope: str = "file user.read", delegated_user: str | None = None) -> str:
    """Issue an access token. With delegated_user, the token acts as that member."""
    env = load_env()
    key = Path(env["WORKS_PRIVATE_KEY"]).expanduser().read_text()
    now = int(time.time())
    payload = {
        "iss": env["WORKS_CLIENT_ID"],
        "sub": env["WORKS_SERVICE_ACCOUNT"],
        "iat": now,
        "exp": now + 3600,
    }
    if delegated_user:
        payload["delegated_user"] = delegated_user
    assertion = pyjwt.encode(payload, key, algorithm="RS256")
    data = urlencode({
        "assertion": assertion,
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "client_id": env["WORKS_CLIENT_ID"],
        "client_secret": env["WORKS_CLIENT_SECRET"],
        "scope": scope,
    }).encode()
    req = Request(TOKEN_URL, data=data, method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req) as r:
            return json.loads(r.read())["access_token"]
    except HTTPError as e:
        raise RuntimeError(f"token error {e.code}: {e.read().decode()[:300]}") from e


def call(method: str, path: str, token: str, params: dict | None = None, body=None):
    """Raw API call. Returns (status_code, parsed_body_or_text)."""
    url = BASE + path
    if params:
        url += "?" + urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
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


def token_for(user: str | None = None, scope: str = "file user.read") -> str:
    """Token for the given member (defaults to WORKS_DEFAULT_USER)."""
    env = load_env()
    u = user or env.get("WORKS_DEFAULT_USER")
    if not u:
        raise RuntimeError("no delegated user: pass user= or set WORKS_DEFAULT_USER")
    return get_token(scope=scope, delegated_user=u)


class ApiError(RuntimeError):
    def __init__(self, status: int, body):
        self.status, self.body = status, body
        super().__init__(f"HTTP {status}: {str(body)[:300]}")


def _ok(st: int, r):
    if not 200 <= st < 300:
        raise ApiError(st, r)
    return r


def _paged(token: str, path: str, key: str = "files") -> list:
    items, cursor = [], None
    while True:
        params = {"count": 200}
        if cursor:
            params["cursor"] = cursor
        r = _ok(*call("GET", path, token, params=params))
        items += r.get(key, [])
        cursor = r.get("responseMetaData", {}).get("nextCursor")
        if not cursor:
            return items


# ---------- verbs (admin plane) ----------

def drives_list(user: str | None = None) -> list:
    r = _ok(*call("GET", "/sharedrives", token_for(user)))
    return r if isinstance(r, list) else r.get("sharedrives", [])  # observed: {"sharedrives": [...]}


def drive_get(sd: str, user: str | None = None) -> dict:
    return _ok(*call("GET", f"/sharedrives/{sd}", token_for(user)))


def files_list(sd: str | None = None, folder_id: str | None = None, user: str | None = None) -> list:
    if sd:
        path = f"/sharedrives/{sd}/files" + (f"/{folder_id}/children" if folder_id else "")
    else:
        path = "/users/me/drive/files" + (f"/{folder_id}/children" if folder_id else "")
    return _paged(token_for(user), path)


def perms_list(sd: str, folder_id: str | None = None, user: str | None = None) -> dict:
    path = f"/sharedrives/{sd}" + (f"/files/{folder_id}" if folder_id else "") + "/permissions"
    return _ok(*call("GET", path, token_for(user)))


def perm_grant(sd: str, target: str, perm_type: str, folder_id: str | None = None,
               user: str | None = None) -> dict:
    t = token_for(user)
    if folder_id:
        st, r = call("POST", f"/sharedrives/{sd}/files/{folder_id}/permissions", t,
                     body={"userId": target, "type": perm_type})
    else:
        st, r = call("POST", f"/sharedrives/{sd}/permissions", t,
                     body={"userId": target, "userType": "USER", "type": perm_type})
    return _ok(st, r) or {"granted": target}


def perm_revoke(sd: str, perm_id: str | None = None, target: str | None = None,
                folder_id: str | None = None, user: str | None = None) -> dict:
    """Delete ONE permission. Bulk 'all-delete' is intentionally unsupported
    (its semantics flipped between WORKS versions: 'open to everyone' vs 'masters only')."""
    t = token_for(user)
    base = f"/sharedrives/{sd}" + (f"/files/{folder_id}" if folder_id else "")
    if not perm_id and target:
        r = _ok(*call("GET", base + "/permissions", t))
        for p in r.get("permissions", []):
            if target in (p.get("userId"), p.get("email")):
                perm_id = p.get("permissionId")
    if not perm_id:
        raise RuntimeError("permissionId not found (give perm_id or target)")
    _ok(*call("DELETE", f"{base}/permissions/{perm_id}", t))
    return {"deleted": perm_id}


def folder_enable(sd: str, folder_id: str, user: str | None = None) -> dict:
    """Enable folder-level permissions (BREAKS inheritance; masters-only until granted)."""
    _ok(*call("POST", f"/sharedrives/{sd}/files/{folder_id}/permissions/enable", token_for(user)))
    return {"enabled": folder_id}


def folder_disable(sd: str, folder_id: str, user: str | None = None) -> dict:
    """Disable folder-level permissions (drops folder grants; restores inheritance)."""
    _ok(*call("POST", f"/sharedrives/{sd}/files/{folder_id}/permissions/disable", token_for(user)))
    return {"disabled": folder_id}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a):
        return None


def download(file_id: str, out_path: str, sd: str | None = None, user: str | None = None) -> dict:
    t = token_for(user)
    url = (f"{BASE}/sharedrives/{sd}/files/{file_id}/download" if sd
           else f"{BASE}/users/me/drive/files/{file_id}/download")
    req = Request(url, headers={"Authorization": f"Bearer {t}"})
    try:
        data = build_opener(_NoRedirect).open(req).read()
    except HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise ApiError(e.code, e.read().decode()[:300]) from e
        with urlopen(Request(e.headers["Location"], headers={"Authorization": f"Bearer {t}"})) as r2:
            data = r2.read()
    Path(out_path).expanduser().write_bytes(data)
    return {"saved": str(out_path), "bytes": len(data)}


def upload(parent_id: str, file_path: str, name: str | None = None, user: str | None = None) -> dict:
    t = token_for(user)
    p = Path(file_path).expanduser()
    data = p.read_bytes()
    name = name or p.name
    r = _ok(*call("POST", f"/users/me/drive/files/{parent_id}", t,
                  body={"fileName": name, "fileSize": len(data),
                        "overwrite": False, "suffixOnDuplicate": True}))
    req = Request(r["uploadUrl"], data=data[r.get("offset", 0):], method="PUT",
                  headers={"Content-Type": "application/octet-stream",
                           "Authorization": f"Bearer {t}"})
    with urlopen(req) as resp:
        return {"uploaded": name, "bytes": len(data), "status": resp.status}


def mkdir(name: str, parent_id: str | None = None, user: str | None = None) -> dict:
    path = (f"/users/me/drive/files/{parent_id}/createfolder" if parent_id
            else "/users/me/drive/files/createfolder")
    return _ok(*call("POST", path, token_for(user), body={"fileName": name}))


def share_create(file_id: str, owner: str, to: str, perm_type: str = "READ",
                 notify: bool = False) -> dict:
    """share-create: puts the folder into the recipient's 'shared with me'. My Drive folders only."""
    t = token_for(owner)
    _ok(*call("POST", f"/users/me/drive/files/{file_id}/share", t,
              body={"members": [{"userId": to, "userType": "USER", "permissionType": perm_type}],
                    "sendNotification": notify}))
    return {"shared": file_id, "to": to, "type": perm_type}


def share_delete(file_id: str, owner: str) -> dict:
    _ok(*call("DELETE", f"/users/me/drive/files/{file_id}/share", token_for(owner)))
    return {"unshared": file_id}


def sharedfolders_list(user: str) -> dict:
    return _ok(*call("GET", "/users/me/drive/sharedfolders", token_for(user)))


def search(query: str, filters: str | None = None, user: str | None = None) -> dict:
    params = {"query": query}
    if filters:
        params["driveTypeFilters"] = filters
    return _ok(*call("GET", "/users/me/drive/search", token_for(user), params=params))
