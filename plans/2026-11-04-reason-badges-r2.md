# 2026-11-04 Reason badges, round 2 (t_93ae9b6b, PR #74)

Cites lesson `docs/lessons/2026-11-04-a-label-from-free-text-matches-its-own-negation.md`: a label must come from one stored source of truth; a stale second source beats the real cause. Same here: a stored reason_code that is never cleared outranks the real cause.

Nate round 1 (comments 518/519 + 15:00 note) changes:
1. reason_code lifecycle. Rule: move to any state other than needs-human -> reason_code = null (sync_transition and queue_rows_to_status). Move INTO needs-human from a different state -> given code, or null. needs-human stays needs-human -> keep stored code; a given code replaces it; weekly re-assert sends no key. Implemented via an `old_state` arg on sync_transition. Tests: park->queued->park-no-code walk ends null + derived label; weekly over needs-human row with stored code leaves key unsent; weekly over queued/live row sends null.
2. tests/reasons.test.mjs: split SQL on /\r?\n/; prove 78/78 under core.autocrlf=true.
3. Couldn't check "Check" line shows raw ce_checks.note, fallback reasonOf.
4. Then (granted on this card): apply db/011_reason_code.sql then db/011_reason_code_backfill.sql to prod, readback (a)-(d), stop and block on any difference. Then dispatch CI on the new head. Do not merge #74.
