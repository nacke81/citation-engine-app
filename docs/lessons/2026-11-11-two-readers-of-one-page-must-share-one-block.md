# Two readers of one page must share one block (t_00a75d04, round 4)

Scoring and the fix list each carried their own idea of "NM's own listing" (a windowed scan in core, a stop-marker block in fixlist). Each passed its own tests, and they disagreed on real pages:
a wrong street scored a match while the fix list showed the diff, and a neighbour's city hid the old city.

Rule: when two code paths judge the same page, one function finds the block and both call it. Never tune a window to make one reader agree with the other.
Gate it with an invariant test over real page shapes in every form (match iff no address/phone diff), not with per-bug cases.
Filters that drop a line as "prose" must match a phrase, never a single word that is also a real street word (Business, Local, Way, of, the).
