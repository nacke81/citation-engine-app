# Plan 2026-10-16: Citation Engine slice 2 (last), fix list catches every wrong value + website (kanban t_93e2b036)

Latest lesson read: none exists (docs/lessons absent in this repo; v1 docs/lessons holds only README.md). Prior plan: plans/2026-10-16-fix-list.md (slice 1, 135ba89). Its "Not done this slice" list is this slice's scope: unknown wrong phones, the website field.

## Decisions
- Compare by normalized value to canonical, not against a stale list. `job/fixlist.py` gets a field extractor that reads only the listing's own block of the saved page text: from each line that starts with the business name, forward until a stop marker ("claim this business", "near me", "similar", "you might also like", "places near", "ratings and reviews", "showing", "featured") or 80 lines. Other businesses' phones/streets on list pages stay out.
- Phone: every phone in the block, digits only, `!= canonical` -> phone diff. Formats ignored. Label "old phone" only when it is on the known-stale list (label, not the test).
- Address (rule, not a URL special case): a diff exists only when the listing SHOWS a street line and it differs from canonical. No street line shown (service-area listing) = no address diff, whatever the business. Street compare: lower-case, punctuation off, Suite/Ste/#, St/Street, Dr/Drive, Blvd/Boulevard etc. folded; type word ignored when one side lacks it; a unit counts only when live shows one and it differs (missing unit = no diff). Zip compared only when on the same line as the street. Label "old address" when it matches the old-street pattern.
- Site: canonical site added to identity (`BIZ[b].site`, local file; tests use a placeholder). Live site read only from labeled/bare-domain/URL lines in the block (not from prose, emails, or Directory hosts). Compare host: scheme, `www.`, trailing slash, path, query/tracking params ignored. Different host -> site diff. No site and no "Website"/"Web" button label in a readable block -> site diff with live "missing". A "Website" button with no URL captured in the text is NOT flagged (the saved text has no hrefs: known limit).
- Name: unchanged from slice 1 (Consltng-Solutions stays a Name fix).
- Store: unchanged (`ce_checks.diffs` jsonb, rows may now carry `label`). No schema change. Page shows the label next to the field chip.
- Demo: re-score stored run 20261016-1130 from pages.local.json (no Directory traffic) via `--backfill`; before = slice-1 counts (NM 9, SCC 5), after = new counts, each new row explained. 390px screenshots from the live page after deploy. If the stored pages cannot show a field, say so; no new real run unless needed.

## Tests (written with the code)
- Python G6 (tests/golden.py), placeholder identity: (a) unknown wrong phone not on any stale list -> Phone diff; (b) site differing only by www/https/slash/tracking param -> no diff; (c) missing site -> "missing"; (d) Suite vs Ste (and St/Street, punctuation, case, phone formats) -> no diff; (e) service-area listing with no street -> no address diff; wrong street shown -> address diff; (f) slice-1 G1-G5 unchanged and still pass. Self-check: a broken comparer must fail (a).
- Node: label passes through fixList; slice-1 page tests unchanged.
- Safety: job path unchanged, no portal seed call, no Directory action; backfill only PATCHes own ce_checks.
