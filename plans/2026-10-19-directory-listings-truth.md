# Plan 2026-10-19: Directory listings tell the truth (kanban t_693dfc92)

Latest lesson read: docs/lessons/2026-09-21-nm-canonical-street-is-an-engine-input.md (v1 repo; this repo has no docs/lessons). Applied: canonical NAP is an engine input, so the "right value" shown for a NAP error comes from the engine's canonical, never from the portal. Prior plan: plans/2026-10-16-portal-write.md. Base: origin/main 1f087a0. Audit: vault build/reviews/2026-10-19-scc-portal-audit.md (Local SEO tab). Source run: cf6e2f6d-5a0e-4b29-9d62-8d02d7078bf3.

## Decisions
- New `job/listing.py` (pure, no network): `resolve(directory, page_url, links, name_re, phones)` returns (url, kind). A permalink is a URL whose path matches the directory's record pattern (YP /mip/, Superpages /bpp/, DexKnows /bp/, MerchantCircle /<slug>-<city>-<st>, Hotfrog /company/, n49 /biz/, Cybo /US-biz/, MapQuest /us/<state>/<slug>-<id>, Google /maps/place/, Apple /place?place-id=, Facebook /<page>/ or /people/). If the matched page itself is a permalink, keep it. Else take the link on that page whose text or card carries the business name/phone and matches the pattern. Else `url=None`, `urlKind="search"`. Bing and Apple search-only matches therefore store null. Search, category and guessed-slug URLs are never stored.
- `job/portal.py` payload per directory adds `urlKind` ("listing" | "search" | null), `napErrors` [{field, live, right}], `reason` + `reasonText` for couldn't-check rows. `napConsistent` is true/false only for found rows, `null` for everything else. Reasons: brownbook unsearchable; yellowbook, localstack no public search; facebook, nextdoor, foursquare login required; yelp, cybo, other walled = bot wall; remaining = "search returned nothing usable".
- `pctFound` computed over checked rows only (found / (found + notFound)); payload also carries `checked`, `catalogTotal: 86`, `directoriesChecked: 25`. UI labels it "of checked" or omits it.
- Portal repo: types.ts adds optional fields; normalize-citations.ts passes them through, keeps napConsistent null, counts NAP errors as `=== false` only; CitationsBlock.tsx splits Found into Correct / NAP error with field + live -> right, shows reason text, "listing has no direct link", scope line "25 of 86 Catalog directories checked weekly.", drops "Fix details" on unchecked rows, mobile stacked layout at <=600px.
- Backfill: `--portal-backfill <UUID> [--pages <run dir>]` re-resolves URLs from saved page links (read-only, no Directory traffic). Run only after Mike merges and deploys the portal PR.
- Item 8: open engine-found cybo/n49 URLs read-only in a browser, no login; report. Truth set untouched. Facebook stays couldn't-check (login required); disagreement reported, not hidden.

## Tests (with code)
- Engine tests/listing_test.py + tests/portal_test.py: SCC YP/Superpages/DexKnows resolve to the 123456789 pages from fixtures; search/category URLs never stored; Bing/Apple search-only -> null + "search"; napConsistent null for unchecked; reasons per directory; napErrors carry live+right; pctFound over checked; no Directory/portal-seed call in the non-production path.
- Portal vitest: normalizer keeps null, error counts; block renders Correct/NAP error rows, reason text, no-direct-link text, scope line, no "Fix details" on unchecked rows, no pctFound 100 over 14 unchecked.

## Not done here (gates)
- Mike merges the portal PR; deploy; backfill; 390/1440 prod screenshots and readback follow that.
