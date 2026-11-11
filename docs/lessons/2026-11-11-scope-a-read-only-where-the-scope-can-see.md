# A scoped read may only overrule the wide read when the scope can see an answer

Plan `plans/2026-11-11-nm-scoring-followups.md` cites the earlier lesson `2026-11-11-a-marker-above-the-answer-is-a-skip-not-a-stop.md`.

Moving a flag from a page-wide read to a block read fixed false positives from neighbours, but silently turned "the block saw nothing" into "the answer is no". The fix is a tie rule: the block wins only when it shows an address of its own; when it shows none, fall back to the wide read. And a not-match must always carry a diff, so when neither read finds the address the diff says needs-check instead of staying silent. Test every scoping change with the answer placed outside the scope (above the anchor, past the cap), not only inside it.
