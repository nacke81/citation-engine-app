# Lesson: a row skipped unread must also be skipped by the sweeps that run after the loop (t_dca17786)

`--any-state --write` may promote a NAMED needs-human row on a match and must touch nothing else. The first version skipped a named live row with a `continue` in the main loop, and the test for "second run writes 0" still failed: the NAP-check sweep after the loop writes `nap_check` onto every `before == live` result, whatever the loop did with it. The skip was real; the write came from a second pass.

Rule: when a guard says "this row is not ours to touch", mark the result (`skipped`) and make every later pass over the results honour the mark. Test "writes nothing" as byte-identical queue file plus zero sink calls, not as "no state change", because a side field is a write.

Also: promote on the one verdict that proves the case (`match`), and give every other verdict its own explicit no-write branch, so a later edit to the generic note path cannot start demoting or annotating a parked row. Prove both guards with mutations that remove each one.
