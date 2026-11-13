# Plan: the under-street state strip must not eat 2-letter city words (t_d64aefb4, PR #105 round 5)

Cites lesson `docs/lessons/2026-11-13-a-prefix-compare-is-a-false-match.md` (latest): a partial compare stood in for the whole. Here the same shape in reverse: a pattern meant to drop a trailing state dropped any 2-letter capital word anywhere.

## Defect (re-QA t_20d66764, verified by Nate at 5150065)
`compare()` under-street city read: `re.sub(r"(?i)\b(<states>)\b|\b[A-Z]{2}\b|\d{5}...", " ", line)`. `(?i)` is a global flag, so `\b[A-Z]{2}\b` also strips St, Mt, El, La, Le, De. Canonical + good same-entity LD + visible "St. Louis, MO" -> false `mismatch` wrong=('city','. Louis'). Main gives nap-incomplete for all of these.

## Change (job/recheck.py only, plus one test file + CI wiring)
1. New `strip_locality_tail(line)`: take the part before the first comma; drop a ZIP; drop a trailing full state name (case-insensitive) or a trailing 2-letter real state abbreviation (any case) only as the LAST token and only when a city word remains. Leading / middle words are never touched.
2. The under-street read uses it instead of the whole-pattern `(?i)` re.sub. State and ZIP checks (`vis_state`, zip) are unchanged.

## Tests (tests/nap_two_letter_city_test.py, CI)
Correct St. Louis / Saint Louis, Mt. Vernon, El Paso, La Crosse, Le Mars, De Pere with "City, ST", "City ST 12345", "City, st" + good LD -> match. Wrong city same state (El Paso canonical, "Dallas, TX") -> mismatch. Wrong state ("St. Louis, IL") -> mismatch. Helper unit cases. Mutation: restore the old whole-pattern re.sub; the St./El cases must fail.

## Evidence
QA qa_r4.py + qa_hostile.py (t_20d66764), Nate's pr105_controls / pr105_qa_check / pr105_twoletter, 109-page replay vs main, full offline suite, leak_check, CI at the exact head. No network, no merge.
