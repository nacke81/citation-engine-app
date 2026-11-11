# Lesson: when the approved city moves, the old city stays a search and evidence alias (t_00a75d04)

Cite: `plans/2026-11-11-nm-r1-identity-release-gate.md`.

Changing the NM record to a new city looked like three identity fields. By grep, the single city string was read in four more places that decide whether an existing listing is still FOUND: the `city in text` evidence flag (a claim needs name + city + one anchor), the search URLs, the guessed-slug URLs (`.../<slug>-<city>`) and the map-page test. Edit only the identity file and every existing listing under the old city stops being claimed or searched, and the scoreboard drops without any listing changing.
Rule: when a client's approved city or street moves, (1) keep the old city as `city_aliases` for evidence AND for every URL the discovery plan builds, (2) list the old streets in `old_street` so an old listing scores differing, never "not found", (3) run the real scorer over the saved pages of the last run before and after, row by row, and show that nothing claimed before is lost.
Second rule: a "city only, no street" address is a valid public form for a service-area business. Make it an explicit per-business rule in the identity file (`RX.city_only`), still require the approved phone, and never let it mask an old street shown next to it. Other businesses carry no rule, so they are unchanged (tested).
Pins: dropping the city-only rule, dropping the evidence flag, dropping the alias, and letting a Nate release count on an SCC row each fail a test (mutation checked).
