# Plan 2026-10-27: Moz Domain Authority per directory, free plan only (kanban t_295208a6)

Latest lesson read: docs/lessons/2026-10-27-recount-from-rows-never-store-a-total.md (one rule on every write path). Here: one function (`snapshot.apply_authority`) sets `authority` on every snapshot write path; nothing stores a copy of DA in the payload builders. Prior plan: plans/2026-10-27-snapshot-nap-fix-blocked-round2.md.

Mike ruling 2026-10-27 (delivered mid-run, overrides the card): free Moz plan only. Hard cap 50 rows per CALENDAR MONTH across all runs. Refresh is yearly: fill domains with no Moz value first (catalog priority first), then re-check only rows older than 365 days. The job runs monthly to use that month's 50.

API (checked against Moz docs 2026-10-27): JSON-RPC 2.0 `POST https://api.moz.com/jsonrpc`, header `x-moz-token`. Method `data.site.metrics.fetch.multiple`, `params.data.site_queries` = up to 50 `{query, scope:"domain"}`; result `results_by_site[].site_metrics.domain_authority`, `errors_by_site[]`. Free quota check: method `quota.lookup`, path `api.limits.data.rows`, result `quota{allotted, used}`. Free tier: 1 request / 10 s, 50 rows per month.

Steps
1. `job/moz.py`: pure parse/select functions + `refresh(db, today, env, fetch, dry)`. Missing token = one log line, skip. Quota lookup failure = skip (fail closed). Allowed rows = min(MOZ_MAX_ROWS (default 50), 50 - rows checked this calendar month (counted from `da_checked_on`), quota remaining). Never above 50 whatever MOZ_MAX_ROWS says. Token never printed (error text scrubbed).
2. `db/007_moz_authority.sql`: add `da_source` (moz|worksheet), `da_checked_on`; backfill `worksheet` where `da` is set; trigger so the seed re-upsert (`da = excluded.da`) can never overwrite a Moz value. Migration file only.
3. Selection order: (a) never checked (`da_checked_on` null) and not Moz-valued, priority asc then worksheet da desc then domain; (b) `da_checked_on` older than 365 days, oldest first. Skip `dead` rows. A domain Moz returns an error for gets `da_checked_on` stamped (no DA) so it cannot starve the queue.
4. Snapshot: `snapshot.apply_authority(payload, {domain: da})` sets `authority` = DA for Moz rows, None otherwise; applied in `portal.write_run` (map loaded by `run.portal_publish` on a real run only; tests pass none, no network).
5. Wire `moz_step()` into the weekly run (after directories_step, before the second portal_publish); non-fatal. The monthly cap makes weekly calls harmless: the first run of a month spends the 50, later ones find 0 left.
6. Tests `tests/moz_test.py` (CI step): fixture -> DA; no token skips; cap (50/month, MOZ_MAX_ROWS=500 still 50, month usage subtracted); order (unchecked first by priority, then >365d only); yearly boundary; snapshot authority for Moz rows and null otherwise; migration shape; no portal seed / live API in test. Dry-run CLI against `tests/fixtures/moz_directories.json`.
