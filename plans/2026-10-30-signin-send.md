# 2026-10-30 — One-time Vaultwarden Send for client sign-in (t_79c39f75)

Latest lesson read: docs/lessons/2026-10-28-a-second-writer-skips-the-first-writers-rule.md (put the rule in the one writer; guard test over every caller).

Base: origin/main 9260aa1 (holds 509eb60), fresh worktree. Pairs with nacke-platform t_02193c0e (columns `signin_send_url`, `signin_send_expires_at` on `citation_verification`).

## Change
1. `job/vault_send.cjs`: runs inside `withVault` (existing per-seat unlock/lock helper). Reads ONE item by id, builds a text Send (maxAccessCount 1, expiration + deletion = now + 7 days, hidden false, no password), pipes the JSON to `bw send create` on STDIN (never argv). Prints only `{url, expires_at}`. Exports `buildSend` / `createSend(bw, ...)` for tests with a stub bw.
2. `job/signin_send.py`: `make_signin_send(client, directory, ...)`.
   - Gate: row `verification_type` in {id-check, document-upload} and state requires_verification. Phone/SMS/postcard/client-email: no Send, no vault call.
   - Fail closed: BW creds unavailable -> one log line, no write. Item `SCC - <directory>` missing/ambiguous (existing `vault_item.resolve_item`) -> one log line, no write.
   - Row write: PATCH `citation_verification?client_id=eq.&directory=eq.` with only the two columns. Dry-run by default; a real write needs `--write` AND `CE_SIGNIN_SEND_WRITE=1` (off until t_02193c0e migration is deployed). Dry run uses a stub table, never the portal.
   - Re-issue: `python job/signin_send.py --reissue --directory D [--write]` mints a fresh Send for a row whose Send is expired/used (same function, always creates).
   - Logs/output: never the password, the Send URL or key. Only directory, item name, expiry.
3. `transitions.record_transition`: after the verification upsert, for id-check/document-upload and when the env flag is on, call `make_signin_send`; failure appends an error and never blocks the queue write. (Types: add `document-upload` to the gate only; VERIFY_TYPES unchanged — portal decides that enum.)

## Tests (tests/signin_send_test.py, tests/vault_send.test.mjs; added to CI)
missing item -> no write; phone/sms/postcard row -> no Send and no vault call; creds missing -> skip, no write; secret absent from all stdout/stderr/log; Send settings; password on stdin only, never argv; write needs flag; reissue works; poisoned urlopen on dry run; static scan: no portal-seed / Directory call.

Not in scope: live Sends-enabled check (t_e15a4194, citation-submitter).
