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
3. Select scopes. Grant only the services your organization actually uses, and note that
   **write is not one decision** — the services differ:

   - **Drive write (`file`)** is usually fine to grant. On a user token it reaches only that
     person's own drive, and WORKS keeps a trash and versions, so mistakes are recoverable.
   - **Mail write (`mail`)** is a bigger step than it looks. The console describes it as
     managing "mailbox, auto-classification, migration, **forwarding**" — so you cannot grant
     "send mail" without also granting the ability to change **forwarding rules**, which is
     the classic data-exfiltration setting. It also lets an agent send mail as that person,
     irreversibly and outward.
   - Granting `mail.read` **and** `mail` together is the well-known risky pair: incoming mail
     is untrusted text that the agent reads, and send is the action it can be steered into.
     Prefer `mail.read` alone unless someone has a concrete need to send.

   Scopes are a property of the app, so this list is the union of what every user of the app
   may request. Widen later when someone shows a need — re-login picks up new scopes.
4. Do **not** enable service-account delegation on this app. Keep the end-user app and any
   admin app separate, so revoking one never disturbs the other.
5. Send the Client ID and Secret to the requester privately, and point them at
   [END_USER_SETUP.md](END_USER_SETUP.md).

**Tell users the scope string.** Clients often default to requesting every scope, and WORKS
rejects the whole login with `invalid_scope` if the app lacks one of them — an opaque failure
to debug from the user's side. Send the exact login invocation along with the credentials,
e.g. for a drive-read/write + mail-read app using `nworks`:

```bash
nworks login --user --scope "file file.read mail.read"
```

Reuse the same app for later requests. Do not create one app per person — that multiplies
the credentials you have to track for no benefit.

## Why this is the safer default

- A leaked user token or secret exposes one account, not the organization.
- Consent is recorded per user, in their browser, rather than granted invisibly by you.
- Only one person — you — needs Developer Console access, so the admin plane stays small.
