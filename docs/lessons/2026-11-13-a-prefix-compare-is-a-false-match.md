# A prefix compare is a false match

Task t_0227a3ce (PR #105 round 4).

**What happened.** The locality supplement compared only the first token of a city and read a visible state only in upper case. Hostile QA found Fort Wayne == Fort Worth, `, oh` ignored, and a first-found JSON-LD block hiding a disagreeing second one. Round 1-3 tests all used one-word cities and upper-case states, so none could fail.

**Rule.** A compare that guards a verdict must be a whole-value compare. When you write `[:1]` or `[0]` on a value that identifies something, ask what else shares that prefix, and write the test with a sibling that does (two-word cities, lower-case input, two blocks that disagree).

**Rule.** Put a check in one function and call it from every path. Two copies of the city check had drifted; one comparator now serves them all.

**Process slip.** The plan for this round was written after the first code pass, not before. The plan now says so; write it first.
