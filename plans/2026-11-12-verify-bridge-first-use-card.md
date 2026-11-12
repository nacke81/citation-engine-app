# Plan: first Verify Now row reaches Nate by itself, then schedule the bridge (t_1a897431)

Cites lesson `docs/lessons/2026-11-12-the-stuck-state-needs-its-own-owner.md` (and `an-agent-gets-a-narrow-helper-and-a-clock`): a state nobody watches needs an owner. A waiting `requires_verification` sms/phone-call row has no request yet, so no sweeper sees it; the bridge becomes its owner by filing one card per row.

Scope (code, small PR):
1. `verify_bridge.py` `first_use_rows(portal)`: one read-only GET on `citation_verification` for `state=requires_verification`, `verification_type in (sms, phone-call)`, allow-listed clients only (same filter as `check_missing`).
2. `file_first_use_cards(portal, card_runner)`: for each row id not seen before, file ONE card to the reviewer on the reviewer board, idempotency key `verify-now-row:<id>`, title `Verify Now: first-use row <directory> (<tenant>)`, body = directory, tenant slug, type, in-allowlist yes/no. No code, no client email, no phone. "Seen" = marker file `first-use-<id>` in the lock dir, written only after the card call succeeded (a failed filing retries next pass). The board's idempotency key is the second guard.
3. `run_pass` calls it after the sweep; a failure there never blocks claim/dispatch. `main` prints `first_use=N`.
4. Tests: two passes over the same row file one card; failed filing retries; non-allow-listed client skipped; wrong state/type never selected; body carries no code/email/phone; allowlist yes/no wording.
Then (outside the branch, after merge): runtime clone ff-pull, one Task Scheduler task matching the postcards pattern (hidden-run.vbs + .cmd), every 1 min, no new instance while running; 3 passes + `--check` pasted.
No portal write, no live Directory, no spend.
