# Plan: recheck._backoff one decision for dry run and write (t_baa09af1, PR #97 follow-up)

Cites lesson `docs/lessons/2026-11-12-a-dry-run-runs-the-same-rules.md`: a dry run must run the same rules as the write. #97 copied the rules into two branches and they drifted: a row already needs-human got a plain backoff on dry run but a second park (a duplicate history entry) on write. 6 live rows are in that state.

Scope, `job/recheck.py` + tests only:
1. New `_backoff_decision(row, day, no_url)` returns one of `already-parked | not-due | park | backoff`. Both dry run and write call it; the branches only differ in whether they call `record`.
2. `already-parked` (state needs-human): no record call, no backoff, recheck_due left as is, `res["already_parked"]=True`, `after` = needs-human; the report says "already parked".
3. Tests (extend `tests/recheck_dryrun_park_test.py`): dry run vs write agree on after/recheck_due/parked for a fresh row at 3 backoffs, a needs-human row at 3 backoffs (and 0 new history entries), and a not-due row. Mutation check: restore the split logic, test fails.
4. Repro on a queue copy only; full suite; CI on the new head.
