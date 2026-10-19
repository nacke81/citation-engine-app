# Plan 2026-10-19: create-queue discovery for 10 Catalog rows outside the weekly 25 (kanban t_76d7b129)

Latest lesson read: none exists (no docs/lessons in this repo). Prior plan: plans/2026-10-16-portal-write.md. Base: origin/main 1f087a0.

## Decisions
- New module `job/create_discovery.py`, GET-only, no import of `portal`, no POST, no login. It does not touch `cfg.DIRS` (that list feeds scoring and the portal payload for the 25; changing it would silently change those counts). The 10 are a separate stage (`CREATE_DIRS`).
- State per Directory/business: `found` (judge_listing claim on the Directory's own search page), `absent` (own-search results page recognised AND the same-method positive control found in the same run), `couldnt` (walled, error, unrecognised page, or no control). No control = couldnt, never absent (golden 2).
- The 10 picks (swaps from Nate's list, one-line reasons in the handoff): kept caring.com, citysquares.com, botw.org, enrollbusiness.com, storeboard.com; swapped out cylex.us (DNS does not resolve, cylex.com is parked), data-axle.com / here.com / neustarlocaleze.biz / dnb.com (data aggregators with no public own-site business search, or walled); swapped in acompio.us, ibegin.com, citylocalpro.com, freelistingusa.com, tupalo.com (reachable plain HTTP, free listing path).
- Output: create rows (`state` queued, `mike_approval` null) only for `absent`. Not wired into `run.py` / portal in this card (portal payload schema is Nate's call); the weekly hook is one call, `create_discovery.run_all(fetcher)`, left for a follow-up.

## Tests (tests/create_test.py, in CI)
- absent only with control; no control -> couldnt; walled -> couldnt; claim -> found.
- self-check: a control-less "absent" is rejected.
- module source has no `portal` import, no POST/PUT/DELETE, no login/signup URL fetched.

## Not done / limits
- No signup, submit, spend or login. Paid rows listed only.
