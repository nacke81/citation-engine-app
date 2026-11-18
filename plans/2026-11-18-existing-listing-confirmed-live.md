# Plan: an existing listing recorded live posts ONE client row "Your <Directory> listing is confirmed live" (t_d9ed56f5)

Cites lesson `docs/lessons/2026-11-18-one-writer-or-the-guard-is-a-wish.md` (latest at start): the invariant (approved_at) lives in one writer, so this card adds a caller of `P.write_deliverables` and nothing else. No second path, no new table name outside portal.py.

## Change (job/transitions.py only, plus tests)
- `build_existing_activity(client_id, row)`: returns a row via `P.deliverable_row` only when state live, `proof.build_action == existing` and `proof.proof_nap_match is True`; else None. Title `Your <directory> listing is confirmed live`; `source_ref citation-existing:<row id>:live`; type citation; channel_label "SEO & Local SEO"; units 1; in_scope true; evidence_url = proof_url; `date_completed` = the proof (confirmed) date.
- `post_existing_activity(client, row_id, ...)`: reads the queue row, posts through `P.write_deliverables` (or dry run: `P.deliverables_request`). Used by record_existing and by a `--existing-activity --row` CLI for the one-time backfill (same helper, same builder).
- `record_existing`: dry run returns `activity_record` + `activities_request`, no write. Real path posts AFTER the status and queue writes succeed; a feed failure lands in `out["errors"]`, never undoes the queue. Gated by `CE_ACTIVITIES_WRITE` like every transition row.
- Wording guard: no "added/built/submitted" in the title.

## Counts (decision: prove, fix if needed)
Consumers found: engine `site/builder.js builderStats` (newLive = result+new; existing is its own bucket, already excluded, t_dc4ffd67) and `ce_weekly_metrics` (reads builderStats, no `existing` key). No code in this repo reads `deliverables`. Platform (read-only look, not edited): activity feed lists rows, tiles read footprint snapshots. Test: before/after `builderRows`/`builderStats` with the two 11/17 rows added: newLive/claimed/fixed unchanged, existing +2.

## Tests (tests/existing_activity_test.py + node count test, CI step)
idempotency (same source_ref twice -> one row), dry run no write, NAP-mismatch no write, real path through P.write_deliverables with approved_at set, title mutation ("added") fails, failure in feed keeps queue, no direct deliverables path, count consumer.

## Then
PR, review, merge under standing rule, runtime clone pulled, backfill the two rows once with `--existing-activity`, prod read-back (read only) of exactly 2 `citation-existing:%` rows with approved_at set.
