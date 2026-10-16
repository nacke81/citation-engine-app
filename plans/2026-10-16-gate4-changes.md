# Plan 2026-10-16: Citation Engine gate 4 changes (kanban t_c0193b8f)

Latest lesson read: none exists (this repo has no docs/lessons; the v1 repo's docs/lessons holds only README.md). Prior plan: plans/2026-10-16-fix-list-slice2.md (3912ef2). Its stated limit, "a Website button with no URL captured is not checked", is item 5 here.

## Decisions
- Page = 3 groups in order Found, Not found, Couldn't check. No "Fix list" group. Rendering moves into pure functions (`site/render.js`) so tests can render the real HTML without a browser.
- Found: one card per directory (dedupe by directory, never more). Errors sort first, then correct ones (plain "correct"). Each error row keeps the slice-2 style (red field label, grey old-phone/old-address chip, red Live, green Canonical, listing URL).
- Not found: card per directory, same strict rule from the job. Couldn't check: card per directory with reason: unsearchable | blocked | error | no result. The reason is written by the job into the existing `ce_checks.note` column (no schema change) and backfilled for run 20261016-1130 from its stored rows.
- "absent" is a DB value only. Page code never contains the literal: internal status is `not_found`; the DB value is mapped in one place from a joined string. Golden (c) greps every served file and the rendered HTML.
- Overview stats: Found, Not found, Correct (found, 0 error rows), With NAP errors (found, 1+ error rows, a website-only row counts), Couldn't check. Correct + With NAP errors = Found by construction and by test. Existing theme colors: .ok green #1e8e3e, .no red #c5221f.
- Old phone: 386-7057 added to the NM `stale_phones` in the local identity.json (outside the repo). Repo carries no real number: CI proves the rule with a second placeholder stale phone; `tests/local_identity_check.py` (skips when identity.json absent) checks the real list by sha256 hash. Hash added to the leak denylist.
- Site links: LINKS_JS and the HTTP fetcher also return the anchor's own text. Job keeps links of anchors whose text/aria says Website/Visit/Web/Homepage, external host, redirect wrappers unwrapped (url=, u=, to=, dest=), and whose card names the business (or the page is not a list page). The hosts go into `diffs_for(site_hrefs=...)`: href host = canonical host -> no row; other host -> Site row; no href captured -> unchanged (never "missing" on list/search pages, never a Site row from a bare button). Hrefs stored in `pages.local.json` (local, gitignored) so backfill can reuse them. No schema change.
- Real run: exactly one, after deploy, with the test-Chrome window count before == after. Sunday schedule untouched. Runtime clone `%LOCALAPPDATA%/citation-engine/app` is fast-forwarded to the deployed commit so Sunday's task runs the new job.

## Tests (written with the code)
- Node (CI `npm test`): (a) a directory with 3 error rows renders as exactly 1 Found card; (b) Correct + With NAP errors = Found for both businesses (placeholder data shaped like run 1130); (c) no "absent" in any file under site/ nor in rendered HTML; couldn't-check never rendered as Not found; (e) card order and colors; couldn't-check cards carry reasons.
- Python golden G7 (CI): (d) site behind a button href compared: matching href -> no row, wrong href -> Site row, redirect-wrapped href unwrapped, other-business href on list page ignored, no href -> no row; (e) second stale phone labeled "old phone", still a Phone row; (f) all earlier tests (G1-G6, leak check) still run. Self-check: a comparer that ignores hrefs fails (d).
- Safety: fixlist still imports no network/portal module; job path makes no portal call or Directory action beyond reading pages.

## Demo
390px screenshots (overview, both business pages) from a local copy with stubbed sign-in on run 20261016-1130 rows. Expected NM Found 11 = 2 + 9, Not found 1, Couldn't check 13; SCC With NAP errors 5. Differences explained if any.
