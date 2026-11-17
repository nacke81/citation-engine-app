# Lesson: a found listing is proof of a listing, not proof of our work (t_dc4ffd67)

Two real SCC listings (maps.apple.com, n49.com) could not be counted because the only proof path assumed NM built or fixed the row: `build_action` was new | claim | fix, and `record_proof` needed an existing live row. Forcing them into one of those would have put work we never did into client-facing "New / Claimed / Fixed" lines.

Rule: when a count and a claim come apart, add a value for the third case (`existing`) instead of reusing the nearest one. Then follow it through every consumer: the proof gate, the re-proof path (recheck must not rewrite it), the weekly result cards, the live total, and the DB check. A single predicate (`BUILD_ACTIONS`) feeds the gate and the test fake of the DB check, so dropping the value fails a test (mutation-checked).

The DB check constraint is the quiet consumer: code that passes every unit test still fails on the first prod write if db/019 is not applied first. The handoff names the statement and who applies it.
