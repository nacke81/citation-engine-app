# Plan 2026-10-27 round 2: nap-fix means a wrong NAP read; weekly write overlays every queue list (kanban t_f6267312)

Latest lesson read: docs/lessons/2026-10-27-recount-from-rows-never-store-a-total.md (a total must come from the rows; here the lesson extends to the class: it must come from one rule that gives the same answer on every write path). Prior plan: plans/2026-10-27-snapshot-nap-fix-blocked.md.

Review (Nate, comment 364, decision final): on real prod data napFix was 21 / blocked 10 (expected 5 / 26), and `write_run` overlaid only fix_queue (7 rows), so the weekly payload dropped the 75 create_queue rows and every live nap_check (Live 8).

1. `snapshot.classify_needs_human`: nap-fix only when `napConsistent is False` on the snapshot row or the queue row's `nap_check.consistent is False`. listing_url, evidence_url, urlKind listing, state found / claimed-unverified alone -> blocked. Drop `has_listing`.
2. `portal.write_run`: default overlay is `buildqueue.load_all_rows()`.
3. `snapshot_dry_run.py FILE [QUEUE]`: same overlay as write_run (all lists) when a queue path is given.
4. Tests: rewrite the G3 cases to the new rule; add a golden from scrubbed real row shapes (fix_queue + create_queue.rows) -> napFix 5 / blocked 26 / live 19 / inProgress 9 / declined 27, same class on finalize-only, fix-rows overlay and all-rows overlay; add a write_run test with a fake portal and create_queue rows (payload holds them, a live create row's nap_check shows and counts in napChecked).
5. Dry run against the prod snapshot copy in Nate's scratch (read only, never committed). No prod env, no writes.
