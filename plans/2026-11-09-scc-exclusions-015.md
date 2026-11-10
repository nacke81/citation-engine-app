# Plan: migration 015, exclude the lead-gen class and agency lead magnets (t_e20d28d9, round 3)

Latest lesson read: docs/lessons/2026-11-09-a-directory-domain-can-carry-the-client-city.md (key a row by the host that serves the listing permalink).
Applied here: a guard that compares a constant to itself proves nothing; pin the behaviour on the data the engine reads.

## Why
The v1 TS branch citation-engineer/t_e20d28d9 @3f81f03 (nacke81/citation-engine) is the wrong repo. It stays unmerged; no PR.
PR #88 merged (be89234). This branch merges origin/main (plain merge, no rebase, no force-push).

## Rulings (Nate, 2026-11-09)
1. Substitutes: only whosinmycity.com passed the add-form probe, and Nate dropped it: its /get-listed/ page is a Pichardo Marketing lead magnet. All other substitutes failed the probe (nearspotusa Cloudflare challenge, yplocal 403, openlocaldirectory contact-only, localcitation login wall, christiancountyconnection no submit path, uscompanieslist data seller, dominion no street address). So NO insert migration and no new row. The number 015 is used for the exclusion update.
2. caring.com: queue row create-caring is rejected, "declined: paid lead form (Mike 10/26)". Lead-gen/referral class (APFM, AgingCare, SeniorAdvisor). But prod ce_directories caring.com is build_eligible true, route agent, so a queue rebuild would cut create-caring again. That is the real defect.
3. n49.com: no change. Prod status for SCC is found, NAP match, permalink; buildrows.decide returns none by design. Pinned by test B10.

## Scope
- db/gen_directories_seed.py: EXCLUDED_REFERRAL (+note), EXCLUDED_AGENCY_LEAD_MAGNET ({whosinmycity.com: "agency lead magnet"}); write_seed and build_sql force build_eligible false, route none, ruling note on those domains in v1 AND hunt rows; build_015_sql; an assert that no excluded domain is promoted.
- db/015_exclude_referral_directories.sql (generated): two UPDATEs, three columns only, no insert/delete/DDL.
- Seed JSON, 002 and 009 regenerated from the generator (`python db/gen_directories_seed.py --hunt`).
- Tests: D12 over ALL seed rows (v1 + hunt), exact 015 text vs generator, 015 shape; B10 n49; B11 full seed on an empty queue gives no excluded row. Count pins: ineligible 52 -> 53, added 101 -> 100, stamped 98 -> 97; "no v1 row false" now exempts EXCLUDED_REFERRAL.
- Mutation check: caring.com back to eligible/agent in the seed makes D2, D12 x2 and B1, B3b x3, B6, B11 fail.

## Gates
No prod apply of 015, no buildrows --write, no Directory request, no portal call. After Nate approves: apply 014 if not applied, apply 015, then buildrows --write.
