# For administrators: issuing User OAuth access to your members

When a member asks for WORKS API access "to use it with AI", the reflex is to grant them
Developer Console access. Don't. Console access is an admin-plane permission: every grant
adds a credential that can be turned into tenant-wide delegation, held by someone who is not
accountable for it and whose usage you cannot audit.

Give them **User OAuth** instead. Register one app for the whole organization and share its
Client ID and Secret. Tokens are then issued per person, after that person logs in, scoped to
their own data.

## One-time setup

1. In the Developer Console, create a Client App for User OAuth.
2. Register a redirect URL — `http://localhost:9876/callback` matches the common desktop
   clients, including [`nworks`](https://github.com/yjcho9317/nworks).
3. Select scopes. **Start read-only** (`calendar.read`, `file.read`, `mail.read`,
   `task.read`) and widen only when someone shows you a need. Scopes are a property of the
   app, so this list is the union of what every user of the app may request.
4. Do **not** enable service-account delegation on this app. Keep the end-user app and any
   admin app separate, so revoking one never disturbs the other.
5. Send the Client ID and Secret to the requester privately, and point them at
   [END_USER_SETUP.md](END_USER_SETUP.md).

Reuse the same app for later requests. Do not create one app per person — that multiplies
the credentials you have to track for no benefit.

## Why this is the safer default

- A leaked user token or secret exposes one account, not the organization.
- Consent is recorded per user, in their browser, rather than granted invisibly by you.
- Only one person — you — needs Developer Console access, so the admin plane stays small.
