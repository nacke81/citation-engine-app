# Plan 2026-10-19: SCC fix queue on the portal + gated one-row submit (kanban t_d43f9e55)

Latest lesson read: none (this repo has no docs/lessons; v1 repo's holds only README.md). Prior plan: plans/2026-10-16-portal-write.md. Base: origin/main 1f087a0.
Rulings (Nate 2026-10-19): work in this repo; step 2 (create discovery) moved to t_76d7b129; step 4 is dry-run only; Vaultwarden login read at run time, fail closed when missing.

## Decisions
- `%LOCALAPPDATA%/citation-engine/queue/scc-fix-create-queue.json` (outside the repo: holds client identity; tests use tests/fixtures/test_queue.json via CE_QUEUE) is the approved Step 1 data (5 fix rows, mike_approval null). Source of truth for rows.
- `job/buildqueue.py (not queue.py: stdlib name clash)`: load + validate rows; `overlay_directories(payload, rows, day)` sets state/stateDate on the SCC portal payload. Queue state -> portal state: queued -> needs-human, submitted/pending-verify/needs-human/live/rejected unchanged. Counts (found/correct/withNapErrors) are NOT changed by the overlay; they stay from the checks.
- Create rows (none yet) would be appended as new directories (napConsistent null, url null). Only SCC; NM never gets queue rows.
- `submit_row(row, ...)`: refuses unless mike_approval is a dict with approved_by, at, and row_id equal to this row's id. Then gets login via an injected Vaultwarden getter; missing -> refuse. DRY RUN ONLY: no Directory call exists in the module; a live adapter is not written. Returns the intended state transition.
- Wire: portal.write_run takes optional queue rows for SCC. Default path loads queue/scc-fix-create-queue.json.

## Tests (queue_test.py, CI)
- Q1 overlay: 5 fix rows show needs-human on SCC, other rows untouched, counts unchanged.
- Q2 mike_approval null cannot submit; approval for another row id cannot; malformed approval cannot.
- Q3 missing Vaultwarden item fails closed; getter raising fails closed.
- Q4 submit never reaches network (no urllib/subprocess/requests in queue.py).
- Q5 NM and FBS get no queue rows; invalid state rejected.
