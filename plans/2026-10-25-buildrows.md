# Plan 2026-10-25: build rails, one queue row per SCC Directory (kanban t_00821936)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-24-tests-no-real-runs.md. Applied from it: stdlib only, no schema change, tests set CE_QUEUE/CE_RUNS to temp before import, base origin/main ab428dd.

## Problem
Lis (citation-submitter) can only work queue rows that carry a Mike approval. Only 6 rows exist. Mike ruled 2026-10-25: build SCC listings across the whole Directory database.

## Design
1. New `job/buildrows.py` (pure `build_rows(queue, dirs, status, checks, day)` + a CLI). Inputs: `ce_directories` (86), SCC `ce_directory_status`, the latest run's SCC checks (diffs, url). One decision per Directory:
   - found + no NAP diffs + permalink (permalink.is_permalink): no row.
   - found + NAP errors: `fix` row in `fix_queue`, listing_url = the permalink (None if the stored URL fails the permalink gate).
   - absent / couldnt_check / unsearchable / never checked (and found-correct without a permalink): `create` row in `create_queue.rows`. Note tells Lis to search first; a find becomes a claim.
   - build_route none, or cost paid: row with state `needs-human`, history note `no-route:` or `paid-tier:`.
   - A Directory that already has a row in ANY list (fix_queue, create_rows, create_queue.rows) is skipped entirely: state, history and approval untouched.
2. New rows get state `queued` (or `needs-human`), `mike_approval` = the blanket ruling verbatim with `row_id` = the row id. Ids follow the existing scheme `fix-<label>` / `create-<label>`, so weekly create_discovery.merge_create_queue (dedupes by id) never doubles them.
3. Ordering: each new row carries `priority` and `da`; top-level `build_order` lists every row id by (priority asc, DA desc, domain). Rows are not reordered in place, so existing rows stay where they are.
4. Idempotent: second run changes nothing and writes nothing. Write is atomic (tmp + os.replace) and a `.bak-<date>-buildrows` copy of the queue is made before any write.
5. Weekly job: `run.py` gets `buildrows_step` (non-fatal, after create_queue_step, before directories_step) using DB directories/status plus this run's in-memory checks. It only ever adds missing rows. `buildqueue.parse_rows` is NOT changed (it would put 80 rows on the portal overlay); transitions.py is NOT changed.
6. Builder half: `site/builder.js` counts a `queued` row as To build even when the finder has no candidate action (never checked, couldn't check); action falls back to the row's `queue_kind` (fix/create -> new). `queue_rows_to_status` already syncs the new rows to `ce_directory_status` (columns exist, no migration).
7. Real write: run the CLI against the live queue and DB sync, report counts by kind and state.

## Tests (tests/buildrows_test.py, node test for builder.js; both in CI)
idempotency; no clobber of state/history/approval; one row per Directory (86 seed Directories -> every one either covered or found-correct); found-correct gets no row; paid/no-route -> needs-human; approval stamp equals ruling; ordering; backup before write; module makes no Directory request and never imports portal/transitions writers.

## Verify
Full local suite, then CI on the PR. Real write: row counts by kind/state, .bak path, 390px screenshot of the builder half.
