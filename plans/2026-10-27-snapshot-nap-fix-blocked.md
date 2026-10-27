# Plan 2026-10-27: snapshot states nap-fix / blocked, summary recomputed from rows, NAP read on every live row (kanban t_f6267312)

Latest lesson read: docs/lessons/2026-10-27-one-read-path-and-evidence-before-close.md (one read path for dry run and write; keep the evidence before the context closes). Applied: the live-row NAP read goes through the same `recheck.read_listing` path as every other row, and the row keeps the result (`nap_check`) on the queue row so the snapshot never has to guess. Prior plan: plans/2026-10-27-batch19-fixes.md.

Facts (Nate, prod read 10/27): 86 rows, needs-human 31 (5 real wrong-NAP, 26 no listing), rejected 27, live 19 (4 true, 1 false, 14 null), submitted 8, pending-verify 1. The payload summary is frozen from the 10/21 scan (found 11, couldntCheck 14, checked 11, directoriesChecked 25).

Decisions (fixed with the portal card t_9611754d): snapshot row states `nap-fix` and `blocked`; summary fields `live, inProgress, napCorrect, napChecked, napFix, blocked, declined`.

Constraints: queue state machine unchanged (needs-human stays internal). No prod write, no Directory action, no portal seed. Tests never load the prod env.

1. New `job/snapshot.py` (pure, no network): `classify_needs_human(queue_row, dir_row)` -> `nap-fix` when a listing exists (listing_url, listing-permalink evidence, queue state found/claimed-unverified, or the row already has napConsistent False), else `blocked`. `finalize(payload)` turns any leftover `needs-human` row into nap-fix/blocked and writes `payload["summary"]` recounted from `directories`.
2. `buildqueue.overlay_directories` classifies and calls `finalize`; a live row's stored `nap_check` sets napConsistent / issues / reasonText. `portal.build_payload` calls `finalize`; the old frozen fields (found, notFound, correct, withNapErrors, couldntCheck, checked, pctFound, directoriesChecked) are dropped, because they cannot be recomputed from rows without a new meaning. `upsert_snapshot` readback compares `summary`.
3. `recheck`: live rows are read every run (`run.recheck_step` passes include_live). After the read a live row gets `nap_check = {at, consistent True|False|None, fields, reason}` written to the queue row only (no state change). Unreadable, not public, no URL, error -> consistent None with a reason.
4. Engine app: `app.js` loads the SCC/NM `footprint_snapshot` (source citation_engine), `render.overviewHtml` shows Live / In progress / NAP correct X of live / Declined from `payload.summary` when present; the old Found / Not found / Correct / Couldn't check cards stay only as the fallback when no snapshot summary loads.
5. `tests/snapshot_summary_test.py` (CI): golden fixture of today's counts (live 19, inProgress 9, napCorrect 4 of 19, napChecked 5, declined 27, napFix 5, blocked 26) + a property test that summary == row recount for many shapes + live-row nap_check cases + no-portal-seed. Update existing tests that asserted the dropped fields. JS test for the cards.
6. `job/snapshot_dry_run.py FILE`: prints the new summary for a snapshot JSON file. No network, no env.
