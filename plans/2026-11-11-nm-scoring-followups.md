# Plan 2026-11-11: NM scoring follow-ups after PR #93 (t_ffa900be)

Cites lesson `docs/lessons/2026-11-11-two-readers-of-one-page-must-share-one-block.md` (latest): every flag that decides a score and every diff the fix list prints must be read from the same block. PR #93 moved three flags into that block; this card moves the last two and fixes the block's edge.

## Gaps and fixes
1. `core.evidence` read `street` / `old_street` page-wide. A neighbour block showing the R1 street gave a false street=Y; About prose with the old street gave old_street=Y with no diff (match=False and no address diff: breaks "match iff no address/phone diff").
   - `fixlist.scoped_flags` also returns `street` and `old_street`, read from `own_block` (only for a biz that already uses scoped flags: city_only rule or aliases; SCC returns None for both and `core.evidence` keeps its page-wide read, so SCC is unchanged).
   - `fixlist.diffs_for`: an old street flag with no street flag emits the "old address" diff even when the block parser found no street line (prose). One rule: not-match => a diff.
2. Yelp "You Might Also Consider" sits above NM's real address. It cannot be a plain STOP_RE entry (the address is below it). New rule in the shared block walker: that marker starts a skipped section that ends at the next resume marker (`About the Business`, `Location & Hours`); the walker resumes there. No resume marker on the page => the marker is not a stop (old behaviour, so N9 keeps the invariant).
3. `address_diff` appended the zip even when the shown line already ends with it ("City, ST, zip zip"). Append only when the shown text lacks it.

## Tests (failing first, in tests/nm_r1_test.py, section N10)
- 1a stale prose with the old street + city-only form + R1 phone => not match, "old address" diff.
- 1b neighbour block shows the R1 street, own card shows a wrong street => not match (no false street=Y).
- 1c neighbour block shows an old street, own card city-only => match (no false old_street).
- 2  Yelp shape with resume marker: neighbour street above NM's real street => NM's own street read; a wrong own street still differs; R1 city-only/full still match. Also a shape with no resume marker keeps N9 behaviour.
- 3  wrong zip diff prints the zip once.
- Mutations by hand: each fix reverted fails its test (output attached).
- Real pages: 7 pages x 6 forms + merchantcircle stale-prose form over run 20261108-1100 pages.local.json (read only), SCC saved pages before/after identical.

## Not
No identity.json change, no queue writes, no submits, no live reads, no SCC behaviour change.

## Round 2 (review round 1, Nate): own street outside the block
Review found: with street/old_street block-only, NM's own canonical street above the name line or past the 120-line walk cap gave match=False with no diff (main: match). Nate's ruling: no new windows or caps; if the block cannot find NM's own street the result is needs-check, never not-match with no diff.
- `scoped_flags`: street / old_street from the block are authoritative only when the block shows an address (a street line, the city or an alias, or the city-only form). Otherwise they stay None and `core.evidence` keeps the page-wide read (same as an empty block).
- `diffs_for`: for a biz with a city_only rule (NM), name + city + canonical phone shown but neither street nor city-only form in the block and no other address diff => an address diff labelled "needs-check" ("not shown in the listing block"). SCC has no city_only rule: unchanged.
- Tests (N10 4 + N9 shapes street-above-name, street-past-cap x 6 forms): written first, 15 failing on 757c569. Mutations: block always authoritative (2 fail); needs-check diff off (6 fail).
- Table: 7 pages x 7 forms plus a 10-row synthetic section for the two shapes; SCC saved pages byte-identical to main.
