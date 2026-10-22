# Plan 2026-10-22: weekly.cmd fast-forwards the runtime clone (kanban t_774a2640)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-22-weekly-proof-writer.md. Applied from it: fail closed, write nothing when unsure. Base origin/main 0871997.

## Design
New job/update.py (stdlib only), called by weekly.cmd before run.py. Always exits 0 so the run proceeds either way.
Steps, each failure prints `UPDATE FAILED: <reason>` and stops updating (run continues on current commit):
1. dirty check: `git status --porcelain`, ignoring __pycache__ lines. Dirty -> fail, nothing touched.
2. `git fetch origin`.
3. Pre-validate origin/main: every job/*.py is read with `git show` and compile()d in memory (no files written, no checkout). Compile error -> fail BEFORE merging, so the clone never moves onto bad code.
4. `git merge --ff-only origin/main`. Non-ff -> fail.
5. Always print `RUNNING ON <sha>` (current HEAD) and `UPDATE OK|UPDATE NOOP|UPDATE FAILED`.
No reset, no force, no rm, no checkout -f.
weekly.cmd body is wrapped in one parenthesised block so cmd parses it fully before the merge can rewrite the file mid-run. Update output goes to the same run log.

## Tests (tests/update_test.py, in CI)
Local bare origin + clone in a temp dir: ff updates + SHA logged; dirty tracked file -> UPDATE FAILED, HEAD and file bytes unchanged; __pycache__ only -> still updates; diverged clone -> failed, unchanged; origin with syntax error in job/*.py -> failed, HEAD unchanged; fetch failure (bad remote) -> failed; weekly.cmd text contains no reset/rm/del/--force.

## Out of scope
Directory traffic, run.py changes.
