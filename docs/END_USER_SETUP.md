# Using NAVER WORKS from an AI agent — as yourself

You are in the right place if you want an AI agent to reach **your own** WORKS mail,
calendar, drive, tasks or boards.

You do **not** want `worksmobile-mcp` (this repository). That is an administrator tool: it
authenticates as a delegated service account that can act as any member of the organization,
so it requires credentials your admin will not — and should not — hand out for personal use.
Being blocked in the Developer Console is that boundary doing its job, not a bug to work
around.

## What to use instead

**User OAuth**, where the token is issued to *you*, after *you* log in through a browser:

|  | Service-account delegation (this repo) | User OAuth (what you want) |
|---|---|---|
| Token acts as | any member of the tenant | you, and only you |
| Who consents | an administrator, once | you, in your browser |
| If the credential leaks | the whole organization | your account |
| Admin rights needed | yes | no |

A ready-made client already exists — [`nworks`](https://github.com/yjcho9317/nworks)
(CLI + MCP server, npm) covers calendar, drive, mail, tasks and boards over User OAuth.
There is no need to write anything.

## What you need from your administrator

One thing: the **Client ID and Client Secret** of a User-OAuth app registered for your
organization, with a redirect URL such as `http://localhost:9876/callback`.

Ask for that — *not* for Developer Console access, and *not* for a service account. One app
serves everyone in the organization; your admin registers it once and shares the two values.
If they need a reference for setting it up, point them at
[docs/ADMIN_ISSUING_USER_OAUTH.md](ADMIN_ISSUING_USER_OAUTH.md).

## Then hand this to your agent

Paste the following into Claude Code, Codex, or whichever agent you use, filling in the two
values you were given:

```
Set up NAVER WORKS so I can use it from this agent.

Ground rules:
- Authentication is **User OAuth**. It must act only as me. Do not set up a service
  account, and do not use delegation. No private key is involved.
- If you already installed `worksmobile-mcp`, do not use it here — that is an
  administrator tool and it will not work with my permissions. Unregister it if present.
- Client ID: <paste>
- **The Client Secret is deliberately not in this prompt.** I will enter it myself.
  If the login needs it, tell me where to put it and wait — do not ask me to paste the
  value into this conversation, do not print it, and do not write it into any file you
  create.
- The redirect URL http://localhost:9876/callback is already registered.

Tasks:
1. Install `nworks` (github.com/yjcho9317/nworks, on npm) — a CLI and MCP server for
   NAVER WORKS covering calendar, drive, mail, tasks and boards.
2. Read its documentation and configure it with the Client ID. Run the browser User OAuth
   login, **requesting only the scopes this app has** — ask me for the exact scope string if
   I have not given you one. Requesting scopes the app lacks fails the whole login with
   `invalid_scope`.
3. Register it as an MCP server for this agent.
4. Verify: check the auth status and run one read-only command (for example, list my
   calendar events). Show me the result.

Cautions:
- Never commit the Client Secret, echo it back to me, or write it into a file you author.
  Keep config under my home directory and check .gitignore.
- If you conclude that a service account or admin rights are required, stop and tell me
  instead of proceeding.
```

## Where the secret should actually go

`nworks login --user` asks for the Client ID and Secret interactively when they are not
already configured, so the simplest safe route is to run that yourself and paste the secret
at the CLI prompt. It never enters the agent conversation that way.

If you are wiring the MCP server instead, put it in the server's `env` block
(`NWORKS_CLIENT_SECRET`) — the package's own docs treat the Client ID as
agent-configurable and the Secret as env-only, for the same reason.

Why bother, when a desktop client's secret is not truly secret? Because this one is
**shared across your whole organization**. A leak does not only expose you: it lets someone
stand up an OAuth consent screen that looks like your organization's official app.

## Notes

- Your Client Secret ends up on your machine. In a desktop client it is not truly secret,
  which is exactly why this path is scoped to your account alone.
- You will only ever see your own data. If a task genuinely needs organization-wide
  access, it does not belong on this path — talk to your administrator about it.
