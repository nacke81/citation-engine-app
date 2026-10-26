# Plan 2026-10-25: auto-recheck pending rows + batch 5/6 fixes (kanban t_64c4d511)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-25-portal-create-url.md. Applied: stdlib only, tests mock every network edge, no schema change (no migration), queue file untouched until t_db09baa9 closes.

1. job/recheck.py: rows in submitted / pending-verify / found (live only with --include-live) that carry a listing permalink (evidence_url, else listing_url, must pass listing.is_permalink). Fetch plain GET; if walled/empty, render in build Chrome CDP 9333. NAP compare to q["canonical"] with fixlist primitives (name, phone digits, street). All match -> proof first (ce_directory_status), then live through transitions.record_transition. Mismatch -> same-state note naming field + shown value (skipped if the last history note is identical). No permalink -> nothing. bbb: resolver searches bbb.org by name + city and stores the /profile/ URL through a same-state transition. Wired into run.py as a non-fatal step + CLI.
   transitions.py: same-state notes allowed on submitted / pending-verify / live too (needs a note, no Activities row, no verification PATCH for a same-state move).
2. transitions.record_transition rebuilds the snapshot overlay from ALL live / pending-verify / submitted queue rows (each at its own last history date), then the moved row last.
3. job/playbooks/bizapedia.py like hotfrog.py (CDP 9333, LISTINGS_IMAP_*), not run live.
4. Website value: bizapedia claim form text says the value must start with https://; its FormatUrl only trims and lowercases (no prepend). Both playbooks send the full https:// URL, tested. Finding written into the vault playbook.
5. job/fill_signup_urls.py: signup_url / claim_url from playbook files + create_discovery.CREATE_DIRS, only when empty, backup first. Run after t_db09baa9 closes.
6. tests/create_test.py: the "division by zero" line is the test's own deliberate failing merge (M7) printing to stderr. Capture that stderr and assert on it; wrap the run so any crash exits non-zero.
