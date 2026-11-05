# Plan: stop hammering directories (t_e34fc55c)

Cites docs/lessons/2026-11-04-every-park-path-names-its-own-reason.md: find every path by grep, not by the known callers. Here: every Directory read goes through the plain/chrome/osm callables in `_recheck_rows`, so one wrapper there covers the search reads and the listing reads. A new second path would skip the guard.

Base: main at 6b7fbcc. Branch citation-engineer/t_e34fc55c-site-spacing. No live sweep; no queue writes except the one live proof run (dry run on a queue copy).

1. `job/sitegate.py` (new): file ledger `%LOCALAPPDATA%/citation-engine/site-guard.json` (env CE_SITE_GUARD), O_EXCL lockfile so two processes serialise. Per domain: min gap 60s (env CE_SITE_GAP), daily cap (bizapedia.com 3), cooldown until next local midnight after a wall. `reserve()` sleeps out the gap, or refuses on cooldown / cap. Same URL re-asked within 5 min (plain then Chrome fallback) is the same read: no extra gap, no extra count. Every reserved read appends a line to `logs/site-reads.jsonl` (ts, domain, waited). `wall()` sets the cooldown and writes ONE line to `logs/site-walls.jsonl`. `wall_counts(7)` for the reports.
2. `job/recheck.py`:
   - `STABLE_READS` 3 -> 2, and the repeat runs only for a row NOT already live (it is about to change state). Live rows get one read. Same rule in dry run and write (t_03a74bae stays: one path).
   - `Page.limited`; `wall_reason(page)` -> quota (bizapedia `pro-search-subscription` in the final URL, or "run out of free searches") or Cloudflare text / 429. New verdict `rate-limited`: no `_backoff`, no write, no demotion; live rows get nap_check None with a reason (existing non-match handling).
   - `recheck(..., guard=None)`: tests with fakes stay unguarded; `main()` and the weekly step turn it on.
   - `--save-pages DIR` / `--replay DIR` (replay: no network, no mail, dry run only, refuses --write/--backoff-only). `--include-live` without `--row` needs `--live-sweep-ok`.
3. `job/run.py recheck_step`: guard on; prints `SITE WALLS (7d)` per domain. `job/workable.py`: same counts in the table.
4. Tests: `tests/sitegate_test.py` (one read per row, gap across 2 processes, cap, cooldown, quota page -> rate-limited with no row change and a single log line, replay byte-identical, `--include-live` refusal). Existing tests that counted 3 reads updated. `build_runner_test` sets CE_RUNS to a temp dir and asserts the real runs dir did not grow. CI: add `sitegate_test`.
5. Live proof: one signed-out dry run on a queue copy, `--row` x3 incl. bizapedia; show reads and logged gaps.

## Round 2 (Nate review: the weekly discovery sweep was unguarded)
- `sitegate.guard_fetchers(core, guard)` wraps `core.HttpFetcher.fetch` and `core.ChromeFetcher.fetch` with the one per-run SiteGuard (gap, cap, cooldown, quota/CF/429 wall -> `wall()`). Refused or walled read = Result with `err "site-guard: ..."`; `classify()` calls it `blocked`, so discovery says `couldnt`, never `noresult`/absent. `discover.own_search_box` (hotfrog/brownbook/n49) reserves through the same guard. `run.discover_live` installs and removes it.
- `sitegate.known_listings(queue, runs)`: queue rows with a listing_url plus the newest earlier weekly run's `found` rows. `discover.plan_or_known`: a known URL is read directly, the search is skipped; once answered (found, or noresult on a capped domain) later methods/passes skip it; the made-up control is not run on a capped domain. SCC stays before NM in BIZS.
- Not routed (named so it is not a surprise): `mapnap.lookup` (google, apple, bing, mapquest map boxes) and `proof.py`/`build_proof.py` read through their own Chrome pages; they are not Directory search reads of the capped domain. Left for a later card if Nate wants them under the ledger.
- Tests: sitegate_test S8. weekly_claim_test points the ledger at a temp dir.
