# A case-insensitive flag is global, and a strip must be anchored

Task t_d64aefb4 (PR #105 round 5).

**What happened.** The city read under the street removed a state with one regex: `(?i)\b(<state names>)\b|\b[A-Z]{2}\b|zip`. `(?i)` applies to the whole pattern, so `[A-Z]{2}` also removed St, Mt, El, La, Le, De, and the state-name part removed "Kansas", "Virginia", "Texas" from the middle of Kansas City, Virginia Beach, Texas City. Round 4 tests used cities with no 2-letter word and no state word, so none could fail.

**Rule.** A strip that removes a state must be anchored to the END of the text (trailing token, optional zip), and with a comma the city is everything before it. Never remove a word from the front or middle of a city.

**Rule.** When a pattern mixes a case-folded part and a case-exact part, split it; `(?i)` cannot be scoped to half of an alternation. Test with city names that contain state words and 2-letter words.
