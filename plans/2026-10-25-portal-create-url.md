# Plan 2026-10-25: portal shows listing link on create rows (kanban t_bb08988c)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-25-buildrows.md. Applied: stdlib only, no schema change, tests use fixtures and temp env, no network.

Problem: buildqueue.overlay_directories appends create rows with url None, so live create rows (bizapedia) show no link.
Fix: for rows whose id starts with `create-` in live / pending-verify / submitted, set url = row evidence_url and urlKind = listing only when listing.is_permalink passes (rejects search/category/signup/success URLs). Other states and fix rows unchanged.
Tests: add to tests/queue_test.py (live/pending-verify/submitted carry url; bbb get-listed/success and search URL do not; needs-human does not).
Data: yellowbook note refresh through transitions.py (same-state needs-human), after queue backup. SCC snapshot rewrite after merge, read back.
