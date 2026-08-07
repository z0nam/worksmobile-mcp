# worksmobile-mcp

**Unofficial** NAVER WORKS (LINE WORKS) **Drive admin** CLI + MCP server, built on the
Developer API's **service-account delegation** (JWT `delegated_user`).

Existing WORKS MCP servers focus on the *end-user* plane (your own mail/calendar/files via
User OAuth). This project covers the *admin* plane that they don't:

- act **as any member** of your tenant via delegation (like Google domain-wide delegation)
- **shared-drive governance**: list drives, inspect `accessibleRange`/`permissionType`,
  grant/revoke drive- and folder-level permissions, toggle folder inheritance (`enable`/`disable`)
- **share-create** ("shared with me" shortcuts), My Drive scaffolding, upload/download, search
- **directory audit**: account-hygiene rules and reconciliation against an external roster —
  find ex-employees who still hold live mail/drive access

> Not affiliated with NAVER / WORKS MOBILE Corp. "NAVER WORKS", "LINE WORKS" and
> worksmobile.com are their trademarks/properties. Official API docs:
> <https://developers.worksmobile.com/>

## Safety design

WORKS Drive permission APIs have sharp edges. This tool encodes them:

- **Every mutating operation requires explicit confirmation** — CLI: `--yes`
  (non-interactive runs refuse without it); MCP: `confirm=true` parameter.
  Agents are expected to ask the human before setting it.
- **Bulk permission delete ("all-delete") is not exposed at all** — its semantics
  flipped between WORKS versions (masters-only vs *open to everyone*).
- Destructive semantics are spelled out in tool docs: drive `accessibleRange`
  PATCH transitions wipe granted permissions; folder `enable` breaks inheritance;
  `disable` drops folder grants.

## Setup

1. In the [Developer Console](https://developers.worksmobile.com/), create an app with
   **service-account delegation**, note Client ID/Secret, create the service account, and
   download the private key. Grant OAuth scopes (`file`, `user.read`).
2. Configure credentials:

```bash
pip install worksmobile-mcp        # or: uv tool install worksmobile-mcp
mkdir -p ~/.config/worksmobile
cp .env.example ~/.config/worksmobile/.env   # then fill in values
```

Config resolution: process env (`WORKS_*`) > `$WORKS_ENV_FILE` > `./.env` >
`~/.config/worksmobile/.env`.

## CLI

```bash
worksmobile doctor                              # what credentials/scopes actually work
worksmobile users --dept 연구                    # members (joint appointments preserved)
worksmobile find 홍길동                          # search by any substring
worksmobile audit --ignore shared-accounts.txt  # account-hygiene findings
worksmobile drift roster.tsv --name-col name    # reconcile against an external roster

worksmobile drives                              # list shared drives
worksmobile drive @2001000000xxxxxx             # accessibleRange / permissionType
worksmobile ls --sd @2001000000xxxxxx           # list files
worksmobile perms @2001000000xxxxxx --folder FID
worksmobile grant @2001000000xxxxxx --target pm@corp.com --type WRITE --folder FID --yes
worksmobile share FID --owner host@corp.com --to pm@corp.com --type WRITE --yes
worksmobile download FID --sd @2001000000xxxxxx -o report.hwp
worksmobile call GET /users/me/drive/files      # raw API escape hatch
```

All read commands accept `--user someone@corp.com` to act as that member.

## MCP server

stdio (local agents — Claude Code, Codex, Cursor, Gemini CLI):

```bash
claude mcp add worksmobile -- worksmobile-mcp
```

```json
{ "mcpServers": { "worksmobile": { "command": "worksmobile-mcp" } } }
```

Streamable HTTP (remote / chat surfaces):

```bash
worksmobile-mcp --transport streamable-http --port 8123
```

> ⚠️ The delegated service account can act as **any member**. If you expose the HTTP
> transport beyond localhost, put real authentication in front of it, or don't.

### Tools

| Tool | Mutating | Description |
|---|---|---|
| `works_drives_list` / `works_drive_get` | | shared drives & settings |
| `works_files_list` | | files of a shared drive or a member's My Drive |
| `works_perms_list` | | drive/folder permissions |
| `works_perm_grant` / `works_perm_revoke` | ⚠ | grant / delete one permission |
| `works_folder_enable` / `works_folder_disable` | ⚠ | folder inheritance gate |
| `works_file_download` / `works_file_upload` | | storage-redirect download / 2-step upload |
| `works_folder_create` | | My Drive folder |
| `works_share_create` / `works_share_delete` | ⚠ | "shared with me" shortcuts (My Drive only) |
| `works_sharedfolders_list` | | a member's received shares |
| `works_search` | | drive search |
| `works_users_list` / `works_user_find` | | tenant members (needs `user.read`) |
| `works_directory_audit` | | account-hygiene findings + dormant-check report |
| `works_directory_drift` | | reconcile accounts against an external roster |
| `works_api_call` | ⚠ | raw API escape hatch |

⚠ = requires `confirm=true`.

### Directory audit: dormant checks

`works_directory_audit` returns `dormant_rules` alongside `findings`. A rule is dormant when
the field it reads is empty across the whole tenant — e.g. if nobody's `leaveOfAbsence` is
ever set, "on leave but not suspended" can never fire. **An empty findings list is not a
clean bill of health**, so the tool says which checks were powerless instead of implying
everything passed. `coverage` shows the fill rate per field.

This matters in practice: on the tenant this was built against, `employeeNumber` was 0/136
and `hiredDate` 1/136 — the HR fields simply were not populated, which is exactly the kind
of thing an audit tool must tell you rather than paper over.

## API notes (hard-won)

- `accessibleRange` is 3-valued: `TENANT` / `DOMAIN` / `MEMBER`. New drives default to
  DOMAIN+WRITE. **PATCH transitions are destructive** (MEMBER→DOMAIN deletes all grants;
  →MEMBER fails while folder-level grants exist).
- Folder-level permissions accept **individual users only** (no org units); the target must
  already be a drive member (undocumented, observed).
- Folder `enable` = masters-only until you grant; `disable` = grants dropped, inheritance back.
- share-create works on **My Drive folders only** — team-drive folders can't produce
  "shared with me" shortcuts.
- A pure service-account token has **no My Drive** (403); hosting requires delegation to a
  real account.
- Upload is 2-step (metadata POST → `uploadUrl` PUT); download is a 302 whose storage
  location **also** requires the Bearer token.
- `GET /sharedrives` responds `{"sharedrives": [...]}` (docs imply a bare array).

## License

MIT
