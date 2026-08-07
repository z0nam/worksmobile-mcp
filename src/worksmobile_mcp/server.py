"""worksmobile-mcp — unofficial NAVER WORKS Drive admin MCP server.

Transports: stdio (default) and streamable-http.
Safety: every mutating tool requires confirm=true; agents must obtain explicit
user approval before setting it. Bulk permission delete is not exposed at all.
"""
from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from . import core

mcp = MCPServer("worksmobile", instructions=(
    "Unofficial NAVER WORKS Drive admin tools (service-account delegation). "
    "Mutating tools require confirm=true — always ask the human user before setting it. "
    "Drive accessibleRange PATCH transitions are destructive; folder enable breaks inheritance."
))

_CONFIRM = ("confirmation required: this tool changes permissions/sharing. "
            "Ask the user, then retry with confirm=true.")


@mcp.tool()
def works_drives_list(user: str | None = None) -> list:
    """List shared drives (id, name, accessibleRange, permissionType, masters)."""
    return core.drives_list(user)


@mcp.tool()
def works_drive_get(sharedrive_id: str, user: str | None = None) -> dict:
    """Get one shared drive's settings (accessibleRange TENANT/DOMAIN/MEMBER, permissionType)."""
    return core.drive_get(sharedrive_id, user)


@mcp.tool()
def works_files_list(sharedrive_id: str | None = None, folder_id: str | None = None,
                     user: str | None = None) -> list:
    """List files/folders. With sharedrive_id: that shared drive; else the delegated user's My Drive."""
    return core.files_list(sharedrive_id, folder_id, user)


@mcp.tool()
def works_perms_list(sharedrive_id: str, folder_id: str | None = None,
                     user: str | None = None) -> dict:
    """List drive-level (or, with folder_id, folder-level) permissions."""
    return core.perms_list(sharedrive_id, folder_id, user)


@mcp.tool()
def works_perm_grant(sharedrive_id: str, target_email: str, perm_type: str,
                     folder_id: str | None = None, user: str | None = None,
                     confirm: bool = False) -> dict:
    """Grant READ/WRITE to a member (drive-level, or folder-level with folder_id). Requires confirm=true."""
    if not confirm:
        return {"error": _CONFIRM}
    return core.perm_grant(sharedrive_id, target_email, perm_type, folder_id, user)


@mcp.tool()
def works_perm_revoke(sharedrive_id: str, perm_id: str | None = None,
                      target_email: str | None = None, folder_id: str | None = None,
                      user: str | None = None, confirm: bool = False) -> dict:
    """Delete ONE permission by perm_id or target_email. Bulk delete is unsupported by design. Requires confirm=true."""
    if not confirm:
        return {"error": _CONFIRM}
    return core.perm_revoke(sharedrive_id, perm_id, target_email, folder_id, user)


@mcp.tool()
def works_folder_enable(sharedrive_id: str, folder_id: str,
                        user: str | None = None, confirm: bool = False) -> dict:
    """Enable folder-level permissions. WARNING: breaks inheritance (masters-only until granted). Requires confirm=true."""
    if not confirm:
        return {"error": _CONFIRM}
    return core.folder_enable(sharedrive_id, folder_id, user)


@mcp.tool()
def works_folder_disable(sharedrive_id: str, folder_id: str,
                         user: str | None = None, confirm: bool = False) -> dict:
    """Disable folder-level permissions. WARNING: drops folder grants, restores inheritance. Requires confirm=true."""
    if not confirm:
        return {"error": _CONFIRM}
    return core.folder_disable(sharedrive_id, folder_id, user)


@mcp.tool()
def works_file_download(file_id: str, out_path: str, sharedrive_id: str | None = None,
                        user: str | None = None) -> dict:
    """Download a file to a local path (follows the storage redirect with auth)."""
    return core.download(file_id, out_path, sharedrive_id, user)


@mcp.tool()
def works_file_upload(parent_folder_id: str, file_path: str, name: str | None = None,
                      user: str | None = None) -> dict:
    """Upload a local file into a My Drive folder (2-step metadata+PUT flow)."""
    return core.upload(parent_folder_id, file_path, name, user)


@mcp.tool()
def works_folder_create(name: str, parent_folder_id: str | None = None,
                        user: str | None = None) -> dict:
    """Create a folder in the delegated user's My Drive (root if no parent)."""
    return core.mkdir(name, parent_folder_id, user)


@mcp.tool()
def works_share_create(file_id: str, owner_email: str, to_email: str,
                       perm_type: str = "READ", notify: bool = False,
                       confirm: bool = False) -> dict:
    """Share a My Drive folder so it appears in the recipient's 'shared with me'. My Drive only (not shared drives). Requires confirm=true."""
    if not confirm:
        return {"error": _CONFIRM}
    return core.share_create(file_id, owner_email, to_email, perm_type, notify)


@mcp.tool()
def works_share_delete(file_id: str, owner_email: str, confirm: bool = False) -> dict:
    """Remove sharing from a My Drive folder. Requires confirm=true."""
    if not confirm:
        return {"error": _CONFIRM}
    return core.share_delete(file_id, owner_email)


@mcp.tool()
def works_sharedfolders_list(user: str) -> dict:
    """List a member's 'shared with me' folders (requires that member as delegated user)."""
    return core.sharedfolders_list(user)


@mcp.tool()
def works_search(query: str, drive_type_filters: str | None = None,
                 user: str | None = None) -> dict:
    """Search drive files (drive_type_filters e.g. 'SHARE_DRIVE')."""
    return core.search(query, drive_type_filters, user)


@mcp.tool()
def works_api_call(method: str, path: str, body_json: str | None = None,
                   user: str | None = None, confirm: bool = False) -> dict:
    """Raw WORKS API escape hatch (path under https://www.worksapis.com/v1.0). Non-GET requires confirm=true."""
    import json as _json
    if method.upper() != "GET" and not confirm:
        return {"error": _CONFIRM}
    body = _json.loads(body_json) if body_json else None
    st, r = core.call(method.upper(), path, core.token_for(user), body=body)
    return {"status": st, "body": r}


def main():
    ap = argparse.ArgumentParser(prog="worksmobile-mcp", description=__doc__)
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8123)
    a = ap.parse_args()
    if a.transport == "streamable-http":
        mcp.run(transport="streamable-http", host=a.host, port=a.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
