# Plan: record proof for a listing NM did not build (build_action `existing`) (t_dc4ffd67)

Cites lesson `docs/lessons/2026-11-16-count-what-you-can-prove.md`: a client-facing number must use the same rule as the claim behind it. Here: a pre-existing SCC listing counts as proofed live, but must never be counted as work NM did (new / claim / fix).

## Decisions (Nate, not re-decided)
1. `existing` is a fourth build_action. 2. New migration `db/019_build_action_existing.sql` widens the check. 3. `transitions.py --record-existing`. 4. Refusals. 5. Every consumer handles it.

## Change
- `job/transitions.py`: `BUILD_ACTIONS += "existing"`; `record_existing()` + CLI `--record-existing --client SCC --domain --proof-url --proof-nap --proof-at [--dry-run]`. One live row in `fix_queue` (kind `fix`: `queue_kind` check allows only fix|create), `proof.build_action=existing`, validated by `check_proof`, status written first through `D.sync_transition` -> `_upsert_status` (same writer family as record_proof), then backup + atomic queue write. Refuses: non-SCC client, bad domain, any row for the directory (queue file or ce_directory_status), proof_url host not domain/subdomain, incomplete proof field, proof_nap_match not true.
- `job/proof.py build_action()`: a row whose stored proof says `existing` keeps it, so recheck `_proof_only` / `_proof_then_live` / proof backfill never rewrite it to new/fix.
- `site/builder.js`: `existing` result row is state `result`, action `existing`: counted in no newLive/claimed/fixed. Add `existing` stat. metrics.js IN_METRIC unchanged (no new weekly line).
- `db/019`: widen the check constraint (drop + re-add in one transaction; same predicate plus `existing`). No view change: the column list is unchanged.
- Tests: `tests/existing_listing_test.py` (create, each refusal, dry-run writes nothing, fake DirDB enforcing allowed set, recheck keeps existing, status-before-queue, no portal/network); `tests/builder.test.mjs` + `tests/weekly_metrics_test.py` existing-counted-live-not-new; `proof_test.py` mirror of allowed set; CI step added.
- Mutation: drop `existing` from BUILD_ACTIONS -> tests fail.

## Not
No live reads, no proof writes for maps.apple.com / n49.com (child card), no portal write.
