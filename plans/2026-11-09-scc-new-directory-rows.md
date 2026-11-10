# Plan: add and promote the SCC hunt-3 Directories (t_9736bbe4)

Revision 2 (review round 1): usaonline.us re-keyed to kentuckyonline.us; lesson rewritten (key by listing-permalink host).

Latest lesson read: docs/lessons/2026-11-05-count-requests-not-code-paths.md ("run the real entry point and count; a guard cannot see a loop above it").
Applied here: the buildrows counts are asserted by running the real `buildrows` against the seed (tests/buildrows_test.py), not by restating a number; and each new row's signup path is one I fetched myself on 2026-11-09 (public GET only).

## Source
Hunt card t_df418e7f table (citation-auditor), rows 1 to 10, re-probed by me with public GETs. Nate (card t_9736bbe4 comments): promote the workable rows, skip ikeanded/verview, leave the chambers out, competitor referral networks stay out.

## Decision per candidate (rows 1 to 10)
PROMOTE (5, free self-serve path seen 2026-11-09):
- kentuckyonline.us (re-keyed from usaonline.us after review round 1: no listing lives on usaonline.us): "Add your business & get free business listing in the home city" -> https://www.kentuckyonline.us/claim-your-business (same Register-USA form, FAQ: free package).
- kentuckyizze.com: "Add Business or Organization", free during launch, no card; find-and-claim.
- findcarez.com: free listing pages (facility, elder-law); fit for a placement/advocacy business is unproven, so the agent parks if only facility/law-firm forms apply.
- elder-care.us: /for-business "List your business free", claim only after confirming ownership.
- findhelp.org: /signup provider claim; nonprofit-leaning, may refuse a for-profit advocate, agent parks.
Listing host per row (where a listing permalink lives; from pages already fetched, no new sweep). The row's domain must be this host's registrable domain (recheck.resolve_by_search, lookup.py:46, mail_scan.host_ok, your_turn_gate.py:53):
- kentuckyonline.us: https://<city>.kentuckyonline.us/profile/... and www.kentuckyonline.us/local/... (city subdomain of the row domain; reviewer-confirmed).
- kentuckyizze.com: https://kentuckyizze.com/ (records "appear as published" on the same host). Same host as the row.
- findcarez.com: https://www.findcarez.com/pages/free-senior-care-listing is the signup page; listing pages are on www.findcarez.com. Same host as the row. No example permalink was captured.
- elder-care.us: https://elder-care.us/<city>-ky (city pages hold the listings). Same host as the row.
- findhelp.org: https://www.findhelp.org/provider/<agency-slug>/<id> (e.g. an area development district agency page). Same host as the row.
No row other than usaonline.us needed a re-key.
Verification method: only elder-care.us states one ("listed only after ownership confirmed", method not stated); it is in account_note. Others stay unknown.

DROP (with reason):
- owensboroonline.us: same USA Online claim form as usaonline.us, one submission covers the network. Duplicate.
- freelistingusa.com: already a Catalog row (v1 seed and TS row 83). Duplicate.
- eldercarematters.com: add-listing is Basic $9/mo, Premium $29, Featured $59. Paid only.
- seniordirectory.com: "List Your Business" goes to /advertise-with-us ("Get Pricing/Info" lead form). Advertising sale, not a free listing.
- 101eldercare.com: no add-listing form found on the KY page or Additional Resources. No submit path.
Not in this tranche by Nate: ikeanded.com, verview.com, the two chambers (Carol is arranging Lea Ann's member access), AgingCare/SeniorAdvisor/Seniorly/PayingForSeniorCare.
Not promoted, rows 11 to 20 and section C: no agent-submittable path seen (phone/email to a coordinator, member login, walled, or paid). chfs.ky.gov Respite Provider Directory is left out: it lists independent respite providers, a poor fit for placement/advocacy, and only a search snippet backs it.

Honest count: 5 rows, not the 15 asked. The hunt itself said about 10 at best and I verified 5.

## Scope
1. db/directories_hunt_seed.json: append 5 rows, cut `cycle3-2026-11-09`, unknown stays unknown (cost free only where a page said free, account/verification unknown), signup_url as observed, build_eligible true, build_route agent, with the note.
2. db/gen_directories_seed.py: `is_hunt` accepts `cycle3-`, TOTAL_ROWS 153, PROMOTED_014 with notes, included in PROMOTED_ALL. Regenerate seed JSON and 009 (009 re-apply is ON CONFLICT DO NOTHING, so prod is untouched by it).
3. db/014_add_scc_hunt3.sql: data only, idempotent INSERT of exactly these 5 rows (ON CONFLICT (domain) DO NOTHING). No update, no delete.
4. Tests: directories_test.py and buildrows_test.py counts follow (153 rows, 67 hunt, 15 promoted, 52 catalog-only), plus a D11 check that 014 names exactly the 5 domains, none of the dropped domains appear anywhere in the seed, and no row has paid cost.
5. Run: full test suite as CI does, `git diff --check`, workable.py before/after on a dry-run copy of the queue (buildrows without --write).

## Out of scope / gates
No prod apply, no `buildrows --write`, no Directory submit/signup/account (citation-submitter owns those). Review request to the reviewer (Nate) happens before the prod apply and the queue write.
