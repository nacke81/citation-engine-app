# Plan: migration 015, SCC substitute Directory rows (t_e20d28d9)

Stacked on PR #88 (feat/scc-hunt3-rows-t_9736bbe4, t_9736bbe4). Retarget to main after #88 merges.

Latest lesson read: docs/lessons/2026-11-09-a-directory-domain-can-carry-the-client-city.md ("key a row by the host where the listing permalink lives, not by the network's marketing domain").
Applied: each candidate is judged on (a) the free add form loads, (b) it takes name + address + phone for a the client city business, (c) it is not lead-gen/referral, (d) the listing host equals the row domain.

## Why this card exists
The v1 TS branch citation-engineer/t_e20d28d9 @3f81f03 (nacke81/citation-engine) is the wrong repo. It stays unmerged; do not open a PR for it.

## Probe evidence (public GET only, 2026-11-09, page HTML read, no submit, no account)
| candidate | (a) form loads | (b) name+address+phone | (c) not lead-gen | (d) host | verdict |
|---|---|---|---|---|---|
| whosinmycity.com | /get-listed/ 200; JS form (onboard.js) | search by name+city (free text "City, ST"), address comes from the Google Places match, phone field editable; the client city not pre-listed (site is Florida-heavy), unproven | free guide, followed link; low-rating branch posts a lead to the site owner, not a referral network | whosinmycity.com/<city>/<biz>/ (sitemap) | PROMOTE. SCC GBP 5.0 >= 4.2 gate (Nate). Agent parks if the Places match or KY is refused. |
| nearspotusa.com | /add-business 403 Cloudflare "Just a moment" challenge | n/a | n/a | n/a | DROP. Add form does not load. |
| yplocal.com | home 403 LiteSpeed | n/a | n/a | n/a | DROP. Site denies plain GET. |
| openlocaldirectory.com | home 200, no add form; /add-listing and /submit 404; only /contact "Business Listing Assistance" | n/a | n/a | n/a | DROP. No self-serve add path. |
| localcitation.site | /add-listing/ 200 but "must be logged in to post new listings"; form not in HTML; page carries spam links | unproven | unproven | n/a | DROP. Cannot prove fields without creating an account (barred). |
| christiancountyconnection.com | submit path unclear (Nate: drop unless real path) | none found | | | DROP. |
| listyourbusiness.us | /add-business redirects to /login; form behind registration; sample KY listing shows no street/phone | unproven | ok | listyourbusiness.us | ALREADY a Catalog row and queue row create-listyourbusiness, state live (queue read). Not a substitute. |
| getlistedusa.com | Add Listing behind login/register | unproven | ok | getlistedusa.com | ALREADY a Catalog row and queue row create-getlistedusa, state live (queue read). Not a substitute. |
| uscompanieslist.com | web3forms form has address+phone but site sells a $499 B2B data list | ok | data-seller, B2B | | DROP. |
| dominionlocalbusinessdirectory.com | /claim form has no street address; $97/mo upsell | fails (b) | | | DROP. |
Honest count: 1 row, not 6. Fewer good rows beat weak ones (Nate).

## Scope
1. db/directories_hunt_seed.json: append whosinmycity.com (cut cycle3-2026-11-09 stays the cycle tag; unknown stays unknown).
2. db/gen_directories_seed.py: PROMOTED_015 + note, TOTAL_ROWS 154, build_015_sql, EXCLUDED_REFERRAL constant (caring.com, agingcare.com, senioradvisor.com, seniorly.com, payingforseniorcare.com, aplaceformom.com).
3. db/015_add_scc_substitutes.sql: insert only, ON CONFLICT (domain) DO NOTHING. No update/delete/DDL. REQUIRES 008.
4. Tests: directories_test D12 (015 shape), count pins 154/68/16, buildrows_test pins, a test that EXCLUDED_REFERRAL is never promoted/seeded as eligible, a test that n49 (found + NAP correct + permalink) gets no row.
5. Dry run: copy the queue, CE_QUEUE on the copy, buildrows (needs DB read; ce_directories lacks whosinmycity until 015 is applied, so the dry run feeds the seed as dirs), then workable.py --queue <copy>.

## n49
Prod ce_directories n49.com: build_eligible true, route agent, cut SCC-38. Prod ce_directory_status SCC n49: last_result found, last_match true, permalink an n49.com/biz/<id>/... permalink. buildrows.decide returns "none" (found, NAP correct, permalink). So the skip is correct and by design: SCC already has a matching n49 listing. 015 cannot and should not change it without falsifying the check. Open question for Nate: the n49 claim status is unknown; a claim row would need a new row kind.

## caring.com
Queue row create-caring is rejected: 10/25 lead form only (HubSpot iframe, required care category), 10/26 "declined: paid lead form (Mike 10/26)". Tagged lead-gen/referral class; pinned in tests so it is never re-promoted.

## Out of scope / gates
No prod apply, no buildrows --write, no Directory submit/account. Review request to the reviewer before the prod apply.
