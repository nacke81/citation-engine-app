# Plan: terminal `skipped` state for NM rows + `--clear-recheck` (t_5ddb67a4)

Cites lesson `docs/lessons/2026-11-13-the-writer-is-the-process-with-the-key.md` (latest): gate a write on a rule the writer itself enforces, and add a mutation that removes the gate and shows a test failing. Here: the NM writer owns the `skipped` matrix; every reader owns its own skip filter and each filter gets a mutation.

Problem (found in t_fbfefb13): `nm_transitions.py --to skipped` is refused (unknown target state), so Nate's ruling on nm-fix-techbehemoths cannot be recorded. A same-state park keeps the old `recheck_due` (techbehemoths still carries 2026-11-18).

Decisions
1. `skipped` is NM-only and terminal. Allowed from `needs-human`, `pending-verify` (NM's pending), `queued` (NM's new). Note required (existing rule). Clears `recheck_due`. Leaving `skipped` is refused (check_transition: unknown current state). `transitions.STATES` is NOT widened, so the SCC writer still refuses `--to skipped`. `buildqueue.parse_rows` accepts the state only on `nm-` rows.
2. Dateless park: option chosen = explicit `--clear-recheck` flag (not implicit clear), on `nm_transitions.py` AND `transitions.py` (a park goes through `transitions.py --client NM`). Refused together with `--recheck-due`. Implicit clear rejected: it would silently drop dates on every note refresh.
3. Readers of the queue to check (named in tests): workable.classify (counts + lists), recheck.candidates (incl. --any-state), mail_scan.select_rows (historical), buildqueue.submit_row (build/live), fit runnable list (queued only), proof.py + lookup.py (WAITING only), buildrows (existing-Directory set: a skipped row still blocks a duplicate row), build_runner.find_row path -> submit_row.
4. Own count: `workable.classify` counts["skipped"].
Tests: tests/nm_skipped_test.py (+ CI step). Mutations: drop the filter in workable, recheck.candidates, mail_scan each fails a test. Full offline suite run.
No live queue write.
