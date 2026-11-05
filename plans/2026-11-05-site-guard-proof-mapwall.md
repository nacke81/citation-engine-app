# Plan: t_f5d80477 site guard for proof.py, build_proof.py and map-box walls (base main e13b390, PR #83 merged)

Cites docs/lessons/2026-11-05-count-requests-not-code-paths.md: count the requests the entry point really makes, not the code paths. Here the entry points are `proof.proof_step` (real default reader path) and `build_proof.visit`, with recording fakes; no network.

Scope (Nate comments 11/05): mapnap's reserve moved to PR #83 and is merged. This card: (1) proof.py + build_proof.py behind the SiteGuard, (2) map-box wall detection, (3) honest read counts.

1. `sitegate.map_wall(res)`: wall reason for a mapnap.lookup dict (google /sorry/ url, "unusual traffic", captcha / verify-human / CF text). A result with a rendered `panel` is never a wall. `guard_mapnap` calls it after the lookup: wall -> `guard.wall(d, ...)` (cooldown + one site-walls.jsonl line), result forced to couldnt (verified False, results 0, note "site-guard: ..."). Next lookup on that domain is refused by reserve.
2. `proof.recheck_verdict(url, canonical, reader, guard, chrome)`: the default signed-out Chrome is wrapped with `recheck.guarded` (same ledger, same cap/gap/cooldown as the weekly fetchers). A refused or walled read gives verdict `rate-limited`; a fresh Cloudflare wall also calls `guard.wall`. `proof_step(guard=)` builds a `SiteGuard()` when no reader is injected; refusal -> row untouched + listed in `limited`; never a mismatch write, never live. `run.proof_step_run` passes the shared guard.
3. `build_proof.visit(pg, d, kind, url, guard, out)`: reserve before every goto; refused -> result `rate-limited`, no goto; challenge / quota page after the read -> `guard.wall`. `main` builds one SiteGuard.
4. Tests (tests/sitegate_test.py S10, no network): map captcha text -> wall + next lookup refused; panel present -> no wall; cap shared (2 core reads + proof read + proof refused at 3); refused proof read leaves the queue row untouched with no `mismatch`; build_proof refused -> no goto; 2-process gap across guard instances/processes.
5. Offline planned reads per domain, before vs after: real discover_all probe (as t_e34fc55c r3) + the proof reads the real queue would plan. Before = Nate's numbers (mapquest 24, bing 20, n49 17, yelp 16, superpages 15, hotfrog 15, bizapedia 3). Note: guard's `same_read` does not merge http and chrome reads of one URL in discover_all; counts here are real requests.

## Result
- Lesson: docs/lessons/2026-11-05-a-default-argument-is-an-unguarded-reader.md. Found while building: `read_listing(url, None, chrome)` defaults plain to `plain_fetch` (real GET); proof now wraps BOTH routes (`plain` and `chrome`) with `recheck.guarded`.
- Tests: tests/sitegate_test.py S10 (20 new checks, 84/84). Offline probe: workspace t_f5d80477/probe_after.py (needs py -3.13 for playwright import).
- Not changed: discover/ladder read counts. `same_read` still merges only a repeat inside one process within 300s; the guard ledger is one read per URL per window, requests are what a site sees.
