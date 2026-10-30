# 2026-10-30 — A secret-handling job returns the capability, never the secret

- The sign-in Send needs the Directory password to enter a Send body. Keep that inside one node process (`vault_send.cjs`, inside `withVault`), pass it to `bw send create` on stdin, and return only `{url, expires_at}`. Python never sees the password, so it cannot log it.
- The Send URL is itself a capability: it is written to the row and never printed. Status strings carry the expiry only.
- Fail closed is a test, not a comment: missing item, missing creds, a crashing runner, and bad output each assert `None`, zero writes, and exactly one log line free of exception text.
- A real dry run must not mint a Send in the vault: it would be an orphan with no row to carry it. Stub the runner to exercise the path.
- Gate by row type at the function door, so a phone/SMS row never reaches the vault at all (assert the runner was never called).
