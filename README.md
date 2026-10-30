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
- **account state**: suspend / restore / create members over SCIM — the one thing the
  Directory API cannot do, on a credential that cannot permanently delete anyone

> Not affiliated with NAVER / WORKS MOBILE Corp. "NAVER WORKS", "LINE WORKS" and
> worksmobile.com are their trademarks/properties. Official API docs:
> <https://developers.worksmobile.com/>

> ### 🙋 Just want to use WORKS yourself? This is the wrong tool.
>
> If you want an AI agent to read *your own* mail, calendar, drive or tasks, **stop here** —
> see **[docs/END_USER_SETUP.md](docs/END_USER_SETUP.md)**. That path takes minutes, needs no
> admin rights, and only ever touches your own account.
>
> This project is for **tenant administrators**. It authenticates with a delegated service
> account that can act as *any member of the organization*, which is why it needs credentials
> a normal member cannot get. If your Developer Console says *"you do not have access"*,
> that is not a setup problem to solve — it is the boundary working as intended.

## Safety design

> ### 🔑 Read this before you run it anywhere but your own machine
>
> This is not a per-user integration. The credential it takes is a **delegated service
> account that can act as any member of your tenant** — read anyone's drive, change anyone's
> sharing. Treat the private key like a domain-admin key, because that is what it is.
>
> **Do not paste these credentials into third-party MCP hosting, an "install/deploy this
> server" button, or a hosted inspector**, however convenient. Those run the server on
> someone else's machine, and handing them this key hands over the whole tenant. Directory
> and marketplace listings of this repo are automated crawls, not endorsements of any
> deployment model — the only configuration this project supports is **local stdio, on the
> administrator's own machine**.
>
> If you genuinely need the HTTP transport, bind it to localhost and put real
> authentication in front of it. Key compromise here is not recoverable by rotating a
> password: until the key is revoked in the Developer Console, the holder is every employee.

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

3. *Only if you need to change account state* (suspend/restore/create): in the same
   console create a **Provisioning app**, enable **SCIM**, and issue its **Long-Lived
   Token** into `WORKS_SCIM_TOKEN`. This is a second, separate credential — see
   [Account state](#account-state-the-scim-plane) for why it is separate and why that
   is a feature.

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

worksmobile suspend alum@corp.com --yes         # block login (reversible, data kept)
worksmobile activate alum@corp.com --yes        # restore login
worksmobile member-create new@corp.com --family Kim --given Minji --yes
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

Streamable HTTP — **for a locally bound endpoint you front with your own auth**, not for
handing to a hosting provider (see the box at the top):

```bash
worksmobile-mcp --transport streamable-http --host 127.0.0.1 --port 8123
```

> ⚠️ Whichever transport you pick, the process holds a tenant-wide admin credential —
> run it where you would run a domain-admin shell, and nowhere else.

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
| `works_member_footprint` | | one member's full reach — the offboarding query |
| `works_scim_status` | | is the provisioning plane usable (separate token) |
| `works_user_suspend` / `works_user_activate` | ⚠ | block / restore login (reversible) |
| `works_user_create` | ⚠ | create a member (occupies a licensed seat) |
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

### Reconciliation: absence from one roster is not evidence

`works_directory_drift` returns `only_works` — accounts with no entry in the roster you
passed. **That is a signal, not proof of departure.** Every roster omits some population:
an HR register may not carry visiting researchers at all; a chat directory cannot hold
people who were never issued corporate mail. Reading "not in this list" as "has left" is
how a current employee loses their account — which is exactly what happened once, and why
the tool now works this way.

Pass `corroborating_rosters` ({label: path}) with every other roster you have. Rows found
elsewhere come back with `seen_in` populated and should be dropped from suspicion. Each
roster is indexed by **email, phone and name**, because no single key is enough — in the
real case that motivated this, the member had no phone on their account and no corporate
mail, so only the name matched.

One trap worth knowing: normalising Korean mobile numbers by stripping `82` is wrong.
Many records carry the country code *and* the trunk zero (`+82 010-…`), so stripping alone
yields `00…` and matches nothing — 40% of one tenant's numbers. Use `directory.norm_phone`.

`blind_spots` covers the harder case: questions the API cannot answer *at all*. The one that
bites is **delegated administrators** — `isAdministrator` is true only for SUPER admins, so an
account that is a sub-admin in the console still reports `false`. Enumerating "who has admin
rights" from this API alone will silently miss them; do that in the admin console.

### Offboarding: collect the footprint *before* you suspend

`works_member_footprint` answers "what can this person reach" in one call. Two things it
encodes that are easy to get wrong:

- **Order.** Suspending the account first is the intuitive move and it destroys your ability
  to investigate: delegation to a suspended account fails, so their My Drive contents and
  received folders become unreachable. Collect first, suspend second.
- **Drive masters are invisible in `/permissions`.** They live on the shared-drive object's
  `masters[]`. A master can grant permissions and change drive settings, so missing them in
  a handover leaves the drive effectively ownerless — the tool reports them separately.

### Account state: the SCIM plane

Suspending an account is not available on the credential the rest of this package uses.
The Directory API exposes `isSuspended` as **read-only**, so for a long time "suspend the
leaver" was a thing a human did in the console — which, on the tenant this was built
against, meant it was *never done*: 0 of 136 accounts were suspended while ex-members kept
live mail and drive.

The write lives on a different API family, reached with its own Long-Lived Token:

```
PATCH /scim/v2/Users/{id}   {"op": "replace", "path": "active", "value": false}
```

**Keeping it on a separate credential is the safety property, not an inconvenience.**

- This token **cannot permanently delete a member.** Even SCIM's `DELETE /Users/{id}` only
  deactivates and preserves the data. The Directory `user` scope, by contrast, ships a real
  `DELETE /users` that erases someone outright — and that is the operation which, in the
  incident behind this repo's reconciliation warnings, cost a current employee their
  account. Granting `user` scope to get suspension would hand the automation an
  irreversible verb it has no business holding. Granting SCIM gives it exactly the
  reversible one it needs.
- `works_user_suspend` **re-reads `active` after the write** and fails loudly if the value
  did not change. A 2xx is not proof; login state is not something to report as done on
  the strength of a status code.
- It refuses `*.serviceaccount@` addresses. Service accounts sit in the same member list as
  people, and suspending the one your own automation authenticates as takes the tooling
  down with it.
- `userName` is resolved by lookup, never guessed: the SCIM path id is not documented to
  equal the Directory `userId`. Zero matches and two matches are reported differently —
  two accounts sharing a `userName` is an alarm, not an empty result.

Two traps worth stating plainly:

- **Leave of absence is a different axis from login.** `leaveOfAbsence` is a console-only
  marker, not a SCIM attribute, and it does **not** block login. Treating "on leave" and
  "suspended" as one state leaves people marked absent who can still sign in — and tools
  that conflate them will report the job done without doing it. These verbs touch `active`
  only, and say so when the marker is left behind.
- **The token has a 90-day sliding expiry that any call renews.** So a scheduled consumer
  that only calls SCIM when it has work to do will sit untouched for 90 days and then fail
  at the first real suspension. Call `scim.keepalive()` on every run, including the empty
  ones, and have `doctor` fail — not warn — when a configured token stops answering.

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
- **Delegation to a suspended account fails.** Every delegated read of that member —
  My Drive, received shares, their footprint — becomes unavailable the moment you suspend
  them. This is the hard version of "collect first, suspend second": it is not that the
  data is gone, it is that your credential can no longer reach it.
- `GET /users/me/drive` returns a **drive-only** quota for the delegated member. There is
  no admin-side endpoint for it and **no mail-volume endpoint at all** — per-member mail
  usage is visible only in the admin console's statistics. Budget for a console trip.
- **Distinguish 403 from 404 before concluding an endpoint does not exist.** Mail paths
  under `/users/me/mail/*` answer `403 has not permission api scope` — they exist and the
  scope is missing. Invented paths (`/users/me/mailboxes`, `/users/me/storage`) answer
  `404 Api not exists`. We recorded "there is no mail API" for a while on the strength of
  a 403, which was simply wrong.
- A mail scope you have not registered in the console is rejected at **token issue** with
  `invalid_scope`, not at the endpoint — so a failing token request tells you about console
  configuration, not about your code.
- Think twice before adding a mail scope to a *delegatable* app. The same key can act as
  any member, so mail-read on it is not "read mail" — it is "open every mailbox in the
  tenant". If you need it, put it on a separate app whose delegation target, retention and
  audit trail you have decided on first.

## License

MIT
