# 2026-11-04 fill-only reason_code command (t_c3087efc)

Cites lesson `docs/lessons/2026-11-04-every-park-path-names-its-own-reason.md`: rows parked by buildrows / walls try 3 store the code on queue history only; carrying it to ce_directory_status is a backfill decision (Nate: a separate fill-only command).

Hard guard: `queue_rows_to_status` (weekly) is untouched and never sends reason_code. Clearing stays in `sync_transition`.

Changes (job/directories.py)
1. `fill_reason_code_plan(db, queue)`: queue rows (same three lists as the weekly path) with state needs-human, last history entry with to=needs-human carrying a code in REASON_CODES, AND a ce_directory_status row (SCC, owner) whose reason_code is NULL. Returns [{id, directory, code, db_value}].
2. `fill_reason_codes(db, queue, write=False)`: dry run by default; with write, one PATCH per row, body is only `{"reason_code": code}`, filtered `reason_code=is.null` so a non-null code can never be overwritten. Never sends null. No status row -> skipped (never creates rows).
3. CLI `python job/directories.py --fill-reason-codes [--write] [--queue PATH]`; dry run prints id, code, current DB value.

Tests: tests/fill_reason_codes_test.py (fake db): fill-only, unknown code skipped, non-needs-human skipped, dry run writes nothing, only-one-column, weekly path still code-free. Run with existing directories_test, reason_code_paths_test.
No prod write: card stops after the dry run is posted for Nate's go.
