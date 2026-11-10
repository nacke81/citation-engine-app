# Lesson: a guard must read the row the engine reads, not the constant that names it (t_e20d28d9)

Cite: `plans/2026-11-09-scc-exclusions-015.md`.

The first exclusion pin (EXCLUDED_REFERRAL) passed while prod caring.com stayed build_eligible true: the test compared the constant to itself and looked only at hunt rows, but caring.com is a v1 row where a null build_eligible counts as eligible.
Rule: pin the data the engine reads. Check every seed row (v1 and hunt), treat null as eligible, and run the real builder (buildrows on the full seed with an empty queue). Then do a mutation check: flip the row back and watch the test fail. A guard you never saw fail is not a guard.
Also: a missing queue row is not a missing Directory (n49 is found and NAP-correct, so buildrows skips it by design). Read the status before writing a fix. And a "get listed" page can be an agency lead magnet; read who receives the form before listing a client there.
