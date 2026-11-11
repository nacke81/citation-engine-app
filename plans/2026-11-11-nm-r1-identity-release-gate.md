# Plan 2026-11-11: NM engine identity to R1 + Nate release gate (t_00a75d04)

Cites lesson `docs/lessons/2026-11-10-queue-ids-share-a-first-label-and-search-echoes-are-not-hits.md`: a label (there a first label, here a city name) is never an identity; before changing it, find every place that compares by it, and run the real code over the live row shapes, not only new fixtures.

## Goal
Engine scores NM against R1 and NM queue rows can be released by Nate without `mike_approval`. Nate's rulings in the card are final.

## Places that read city / street (checked by grep, not by memory)
- `core.evidence` / `judge_listing` / MAPDIRS branch: `city` flag is `city in text`. After the move to Gallatin every existing Nashville listing would fail the city test. Fix: city flag also true for `city_aliases` (NM: Nashville).
- `core.plan_for` + `cfg.search_url` / `pattern_urls`: built from the single city. Fix: search/pattern URLs for the city AND every alias, de-duplicated (`discover.plan_or_known` already de-dupes).
- `judge.nap_flags`: `match = street and phone`. New: also match when the page shows `Gallatin, TN` (RX.city_only) with NO street and NO old street, plus the R1 phone. Gated on the identity carrying `RX.city_only.<biz>`; SCC and FAKE have none, so they are unchanged.
- `fixlist.diffs_for`: already "no street shown = no address diff"; old street = diff. Pin by test only.
- `recheck.compare` is SCC-bound (refuses a non-SCC queue phone); not touched. Stated in the handoff.
- `buildqueue.approval_ok` / `submit_row`: the only writer gate on `mike_approval`. `workable.py` prints it.

## Changes
1. identity.json (done first, backed up `.bak-t_00a75d04`, read back): BIZ.NM street/city/zip, `old_street` both, `city_aliases`, RX.street/old_street/city_only NM, CANON.NM.address. Phone not touched.
2. `tests/test_identity.json`: placeholder equivalents (Birch Media) so CI exercises the same rules without the client's data.
3. Code: core, cfg, judge as above.
4. Gate: `buildqueue.approval_ok` accepts `row.approval == {by:"nate", card:"t_...", at:<iso>, row_id:<id>}` only on NM rows (id starts `nm-`); `mike_approval` rule unchanged for everything else. `submit_row` records with the row's own client, so an NM row can never be recorded into the SCC queue (transitions stay SCC-only and refuse NM, fail closed).
5. `job/release.py --release <ids> --card <id> [--queue path] [--dry-run]`: only the NM queue file, only `nm-` rows that exist, backs up `.bak-<card>`, atomic write, stamps `approval`, never touches `mike_approval` or state.
6. Tests `tests/nm_r1_test.py` (added to CI): the 8 card cases + alias discovery + release command + mutation checks. Mutation check run by hand: drop the Gallatin-only rule, test fails.
7. Before/after dry run over saved pages (latest weekly run dir) with the old vs new identity, row by row, no network.

## Not
No submits, no live sweep, no SCC rows/identity, no CapSolver, no legacy TS repo.
