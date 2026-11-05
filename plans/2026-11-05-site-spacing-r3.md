# Plan: t_e34fc55c r3 (PR #81 merged as c9e0e19; Nate round-2 execution review)

Cites docs/lessons/2026-11-05-a-verification-run-is-a-read-of-someone-elses-site.md: count reads by the URL actually requested, not by the code path that asked. Here the measure is "identical URL fetched twice in one run", asserted through the real `discover_all`.

Base: main c9e0e19. Branch citation-engineer/t_e34fc55c-r3. No live reads.

1. `discover.plan_or_known(method, d, b, transport)`: a known URL is read ONCE per transport (first method only). On a miss, later methods use `plan_for`. Phase A passes "http", the ladder passes its tag.
2. `sitegate.known_listings`: collect all found rows per pair from the newest run; rank resolver row > url passing `permalink.is_permalink` > first found. Queue URLs rank by the same gate, ties keep the queue. Map-search pages (core.MAPDIRS) are planned with kind="search" so the judge stays "map page text".
3. `sitegate.guard_mapnap(lookup, guard)`: reserve per domain (key=tag); refusal returns a not-verified dict (couldnt, never noresult). `run.discover_live` uses it in the existing lk wrapper.
4. Tests in sitegate_test S9: real discover_all with fake fetchers, JS shell, known URL -> exactly 1 fetch per transport, repeat count 0, a miss falls back to the search plan; resolver wins; map kind; mapnap cap/cooldown -> original not called, couldnt.
5. Offline planned reads per domain + identical-URL repeat count, from the real queue + 11/01 run.

## Round 3 result
- Lesson: docs/lessons/2026-11-05-count-requests-not-code-paths.md. Added: same-url filter and in-plan dedupe (a found search page is the search URL; NM mapquest pattern lists one URL twice).
