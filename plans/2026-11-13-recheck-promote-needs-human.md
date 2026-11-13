# Plan: recheck --any-state --write promotes a NAMED needs-human row to live (t_dca17786)

Cites lesson `docs/lessons/2026-11-13-first-found-must-not-hide-the-rest.md` (latest): a decision made on one source must not silently cover the cases that source does not decide. Here: "the read matched" decides a promote ONLY; every other verdict on a parked row decides nothing and must leave it parked.

Problem: `--row create-nextdoor --write` reads 0 rows (candidates() skips needs-human) and `--any-state` refuses `--write`, so a client-finished ID-check row needs a hand transition (transitions.py needs complete Proof, only recheck builds it).

Scope (job/recheck.py + tests/recheck_promote_test.py + CI step + lesson):
1. `recheck()`: `--any-state` still needs `only` and still refuses `backoff_only` / `proof_live`; `write` is now allowed.
2. `_recheck_rows`: with any_state and write, a named row that is NOT needs-human is skipped unread (note says so); the write is for parked rows only. For a needs-human row: `match` -> `_proof_then_live` (the same writer normal live writes use: Proof, ce_directory_status, citation_verification live + verified_at, client activity). Any other verdict -> no `record()` call at all (no demotion, no note write); the verdict is printed and the row stays parked.
3. `main()`: `--any-state` refused with --backoff-only / --proof-live / without --row; `--write` allowed.
4. One site read per row: unchanged path (read_listing via guard).
Tests (offline, fakes): match -> live, complete Proof, verification PATCH live with verified_at, activity; nap-incomplete / mismatch / unreadable / wall -> byte-identical queue; `--any-state --write` without --row refused (function + CLI); other rows untouched and second run writes 0; non-needs-human named row not touched; mutation (needs-human guard dropped) must make the no-demote test fail.
No --write on prod data.
