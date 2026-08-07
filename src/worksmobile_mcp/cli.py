"""worksmobile — unofficial NAVER WORKS Drive admin CLI (service-account delegation).

Safety: write/permission commands refuse to run without --yes (non-interactive aborts).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import core


def _print(obj):
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, ensure_ascii=False, indent=1))
    else:
        print(obj)


def _confirm(args, msg: str):
    if getattr(args, "yes", False):
        return
    if sys.stdin.isatty():
        if input(f"{msg} — proceed? [y/N] ").strip().lower() == "y":
            return
        sys.exit("aborted")
    sys.exit(f"REFUSED (non-interactive): {msg}\nRe-run with --yes after user confirmation.")


def main():
    ap = argparse.ArgumentParser(prog="worksmobile", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help):
        p = sub.add_parser(name, help=help)
        p.add_argument("--user", help="delegated member email (default: WORKS_DEFAULT_USER)")
        return p

    p = add("token", "issue a delegated access token")
    p.add_argument("--scope", default="file user.read")

    add("drives", "list shared drives")

    p = add("drive", "get shared drive info (accessibleRange etc.)")
    p.add_argument("sd")

    p = add("ls", "list files (--sd for a shared drive, else My Drive)")
    p.add_argument("fid", nargs="?"); p.add_argument("--sd")

    p = add("perms", "list drive/folder permissions")
    p.add_argument("sd"); p.add_argument("--folder")

    p = add("grant", "grant permission [--yes required]")
    p.add_argument("sd"); p.add_argument("--target", required=True)
    p.add_argument("--type", choices=["READ", "WRITE"], required=True)
    p.add_argument("--folder"); p.add_argument("--yes", action="store_true")

    p = add("revoke", "delete ONE permission (bulk delete unsupported) [--yes]")
    p.add_argument("sd"); p.add_argument("--perm-id"); p.add_argument("--target")
    p.add_argument("--folder"); p.add_argument("--yes", action="store_true")

    p = add("enable", "enable folder-level permissions (breaks inheritance) [--yes]")
    p.add_argument("sd"); p.add_argument("fid"); p.add_argument("--yes", action="store_true")

    p = add("disable", "disable folder-level permissions (restores inheritance) [--yes]")
    p.add_argument("sd"); p.add_argument("fid"); p.add_argument("--yes", action="store_true")

    p = add("download", "download a file")
    p.add_argument("fid"); p.add_argument("--sd"); p.add_argument("-o", "--out", required=True)

    p = add("upload", "upload a file to My Drive (2-step flow)")
    p.add_argument("parent"); p.add_argument("file"); p.add_argument("--name")

    p = add("mkdir", "create a My Drive folder")
    p.add_argument("name"); p.add_argument("--parent")

    p = add("share", "share-create a My Drive folder (recipient's 'shared with me') [--yes]")
    p.add_argument("fid"); p.add_argument("--owner", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--type", choices=["READ", "WRITE"], default="READ")
    p.add_argument("--noti", action="store_true"); p.add_argument("--yes", action="store_true")

    p = add("unshare", "remove a share [--yes]")
    p.add_argument("fid"); p.add_argument("--owner", required=True)
    p.add_argument("--yes", action="store_true")

    add("sharedfolders", "list a member's 'shared with me' folders (--user)")

    p = add("search", "search drive")
    p.add_argument("query"); p.add_argument("--filters", help="e.g. SHARE_DRIVE")

    p = add("call", "raw API call (escape hatch; non-GET needs --yes)")
    p.add_argument("method"); p.add_argument("path")
    p.add_argument("--body"); p.add_argument("--yes", action="store_true")

    a = ap.parse_args()
    try:
        if a.cmd == "token":
            print(core.token_for(a.user, a.scope))
        elif a.cmd == "drives":
            for d in core.drives_list(a.user):
                print(f"{d.get('sharedriveId','?'):>20}  {d.get('accessibleRange','?'):>6}"
                      f"/{d.get('permissionType','?'):<5}  {d.get('name','')}")
        elif a.cmd == "drive":
            _print(core.drive_get(a.sd, a.user))
        elif a.cmd == "ls":
            for f in core.files_list(a.sd, a.fid, a.user):
                print(f"{f['fileType']:>6}  {f.get('fileSize',0):>12,}  {f['fileId']}  {f['fileName']}")
        elif a.cmd == "perms":
            _print(core.perms_list(a.sd, a.folder, a.user))
        elif a.cmd == "grant":
            _confirm(a, f"[grant] {a.sd} {'folder '+a.folder if a.folder else 'drive'}: {a.target} <- {a.type}")
            _print(core.perm_grant(a.sd, a.target, a.type, a.folder, a.user))
        elif a.cmd == "revoke":
            _confirm(a, f"[revoke] {a.sd} {'folder '+a.folder if a.folder else 'drive'}: {a.perm_id or a.target}")
            _print(core.perm_revoke(a.sd, a.perm_id, a.target, a.folder, a.user))
        elif a.cmd == "enable":
            _confirm(a, f"[enable] {a.sd} folder {a.fid} — inheritance will BREAK")
            _print(core.folder_enable(a.sd, a.fid, a.user))
        elif a.cmd == "disable":
            _confirm(a, f"[disable] {a.sd} folder {a.fid} — folder grants will be dropped")
            _print(core.folder_disable(a.sd, a.fid, a.user))
        elif a.cmd == "download":
            _print(core.download(a.fid, a.out, a.sd, a.user))
        elif a.cmd == "upload":
            _print(core.upload(a.parent, a.file, a.name, a.user))
        elif a.cmd == "mkdir":
            _print(core.mkdir(a.name, a.parent, a.user))
        elif a.cmd == "share":
            _confirm(a, f"[share] {a.owner}'s folder {a.fid} -> {a.to} ({a.type}, noti={a.noti})")
            _print(core.share_create(a.fid, a.owner, a.to, a.type, a.noti))
        elif a.cmd == "unshare":
            _confirm(a, f"[unshare] {a.owner}'s folder {a.fid}")
            _print(core.share_delete(a.fid, a.owner))
        elif a.cmd == "sharedfolders":
            if not a.user:
                sys.exit("--user required")
            _print(core.sharedfolders_list(a.user))
        elif a.cmd == "search":
            _print(core.search(a.query, a.filters, a.user))
        elif a.cmd == "call":
            if a.method.upper() != "GET":
                _confirm(a, f"[raw {a.method.upper()}] {a.path}")
            body = json.loads(a.body) if a.body else None
            st, r = core.call(a.method.upper(), a.path, core.token_for(a.user), body=body)
            print(f"HTTP {st}")
            _print(r)
            sys.exit(0 if 200 <= st < 300 else 1)
    except core.ApiError as e:
        print(f"HTTP {e.status}", file=sys.stderr)
        _print(e.body)
        sys.exit(1)
    except RuntimeError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
