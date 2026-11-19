# Plan: one card when a Verify Now send closes failed/signin_failed (t_73db4569)

Cites lesson `docs/lessons/2026-11-18-exit-code-must-say-the-write-failed.md` (latest by mtime at start): a follow-up side effect (the card) must never hide or flip the primary result, and its failure must be visible (log line), so the card call is best-effort, logged, and tested through the real `VerifyRpc.finish` with a raising fake.

## Step 1 finding (base 3ef1204, origin/main)
Nothing alerts on signin_failed. `grep -n kanban job/verify_*.py` finds only the sweeper card (`card_argv`, could_not_start / post-send stuck) and the first-use row card. No Telegram path. So build it.

## Change
- `job/verify_bridge.py`: `signin_card_argv(request_id, stage, now)` + `file_signin_card(...)`. Called from `VerifyRpc.finish` (the one place every close goes through: verify_send, verify_step `fail`, sweeper, fence) AFTER the portal write succeeded and the end evidence was saved, BEFORE `SB.finalize` deletes the stage file. Fires only for status `failed` + fail_code `signin_failed`.
- Card: `hermes -p <reviewer> kanban --board citations create`, assignee reviewer, idempotency key `signin-needed-<tenant>-<directory>-<YYYY-MM-DD>` (UTC date of the close), title `<TENANT> <directory>: sign-in needed for Verify Now (client retries after 24h)`, body: tenant, directory, request id, fail time, evidence screenshot path (end > signin > any png, else txt), "reCAPTCHA sign-ins need a human in the NM Chrome (port 9334)". No code/phone/email.
- Best effort: any error logs one line and never changes the close. `CE_NO_CARDS=1` skips (tests' tripwire), like the other cards.
- Tests in `tests/verify_bridge_test.py`: signin_failed close -> 1 card with the expected argv; second same day -> same key (board dedupes; FakeCards by_key == 1); send_failed / timeout / could_not_start / verified -> 0 cards; card runner raising -> close still succeeds and logs; no Telegram/portal call. Mutation check: removing the status gate fails the test.

## Round 2 (review changes_requested, same lesson cited above)
Card body only: tenant Chrome from `verify_send.TENANT_BROWSER` (unknown -> "no browser configured"); stage `reason` shown, one action line for CAPTCHA/signed-out and vault/login; Nate "do not sign in, ONE Todoist ask, vault -> client seat" line; key date + "Failed at" in America/Chicago. Tests: SCC/NM/unknown tenant, reason/no reason, Nate line, 01:30Z 11/20 == 20:00Z 11/19 key, midnight rollover. Trigger and best-effort behavior unchanged.
