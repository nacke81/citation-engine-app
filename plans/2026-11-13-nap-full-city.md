# Plan: compare the whole city, read visible state in any case, never match on disagreeing same-name JSON-LD (t_0227a3ce, PR #105 round 4)

Cites lesson `docs/lessons/2026-11-13-first-found-must-not-hide-the-rest.md` (latest): the first thing found must not stand in for everything. Here: the first word of a city stood in for the whole city, and the first same-name JSON-LD block stood in for all of them.

Written in the same session as the code, after the first fix pass (the process slip is noted in the lesson `docs/lessons/2026-11-13-a-prefix-compare-is-a-false-match.md`).

## Defects (hostile QA t_ebbedd02 on a6a5fa4)
- `F._tok(city)[:1]` compared only the first city word: Fort Worth / Fort Smith matched Fort Wayne.
- The supplement read a visible state only when upper-case: `Fort Wayne, oh` / `Exampleton, tn` read as a bare city line and the JSON-LD filled the rest.
- Same-name JSON-LD blocks that disagree (good then bad street, good then wrong city) were resolved by taking the first.

## Change (job/recheck.py only, plus tests / CI wiring)
1. `ctok` / `city_same`: one city comparator, ALL tokens (case, punctuation, hyphen, apostrophe ignored; Saint=St, Fort=Ft, Mount=Mt). The canonical side drops a trailing `ST zip` when the address has no comma before the state. `tail_ok` lets a no-comma text run end with a state / zip, nothing else. Used by: prose_street, the structured-address path, the same-line street+city check, the under-street reads, the supplement.
2. `vis_state`: 2-letter state in any case (lower/mixed case accepted only when a real state) or a full name; used for every under-street line. Same-line fragments accept a full state name alone.
3. `structured_address(same_entity=True)`: when more than one same-name block exists and they differ on street / city / state / zip, return None (no supplement, never match), whatever the order. F14 and F15 now agree.
4. F21 (WebSite/Place-typed block with the business name and the correct address -> match) is accepted by Nate; unchanged and pinned by a test.

## Tests (tests/nap_full_city_test.py, wired into CI)
Fort Worth / Fort Smith LD; visible bare / `, IN` / same-line Fort Worth; `Fort Wayne, oh` / `ohio`; `Exampleton, tn` vs `, ky`; @graph-nested wrong city; both orders of bad-street and wrong-city blocks; agreeing duplicates; real-shape fixture; Saint/St.; 3-part and 2-part canonical. Three mutations (first-token compare, upper-case-only state, first-block-wins) each flip their cases.

## Evidence
QA ev/qa_hostile.py, Nate's pr105_controls.py / pr105_qa_check.py, saved-page replay (109 pages, main vs head, full diff), full offline suite, leak_check. No network, no real queue opened, no merge.
