# Plan 2026-10-24: permalink gate on found rows (kanban t_535d1f78)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-22-weekly-self-update.md. Applied from it: fail closed, never destructive, stdlib only. Base origin/main 39e4b87.

## Problem
Run 20261018-1100 stored search and category pages as found listings (7 of 10 SCC found rows). `fixlist.SEARCHY_URL_RE` is never applied to a stored found URL.

## Design
1. New `job/permalink.py` (stdlib). `LISTING_SHAPES`: host -> regex over path (or full URL for bing). `is_permalink(dir, url) -> (bool, reason)`:
   - empty URL fails (`empty url`).
   - `fixlist.SEARCHY_URL_RE` match fails (`searchy url`), except a Bing `local_ypid` permalink (it lives on a /maps/search path).
   - host in LISTING_SHAPES must match its shape (`not a listing shape`), else fails.
   - host with no shape passes if not searchy; the caller marks `permalink_unverified`.
2. Choke point: `run.build()`. Every row bound for rows -> app DB (ce_checks), portal snapshot, Directory database, build queue and Proof is a `checks` entry from `build()`. After the final `url` is computed (including the existing links resolver), `permalink.apply_gate(c)` runs. Fail -> `result=couldnt_check`, `note="no permalink"`, `url=None`, and the old URL kept in local key `_rejected_url`. Match fields, diffs and `_claim`/`_proof` are cleared so nothing downstream treats it as found. `comb` is updated so the guards and score agree with the checks.
3. No schema change: `rejected_url` and `permalink_unverified` are local `_` keys (already stripped before the ce_checks write). `note="no permalink"` is an existing column. The portal payload gets reason `no permalink` (existing `reason`/`reasonText` fields) and a `permalinkUnverified: true` key only when set.
4. Dedup: `judge.combine` orders found rows so one whose URL passes the gate wins over one that does not (stable otherwise).
5. Tests `tests/permalink_test.py` (in CI): known good pass, known bad fail, fixture `tests/fixtures/found-rows-20261018-1100.jsonl` (SCC + NM found rows) gives 0 found rows with searchy or category URL after the gate, build() flips and keeps `_rejected_url`, dedup, unverified host, no network or portal call.
6. Dry check script `tests/dry_check_run.py <rows.jsonl>`: read only, before/after per business, flipped rows.

## Out of scope
Resolver (next card), Directory traffic, queue/DB/portal hand edits, schema.
