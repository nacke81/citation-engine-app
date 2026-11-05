# 2026-11-05: rebuild a past week only where every possibility the data allows gives the same number

- The six queue-driven tiles (To build, Waiting, Needs a person, results) are computed from current-only inputs (claim_status, agent_access, proof fields) plus a date-only, append-only queue history. Replaying history alone would have produced confident zeros that are really unknowns.
- The honest rebuild enumerates every state each Directory could have been in on the run day (before the first move: absent or queued; a move on the run day itself: either side; claim and access: both), runs the REAL tile function (`builderRows`) per possibility, and fills a metric only when min == max. Otherwise the cell is a gap (null) and the dry run prints the possible range.
- A zero is allowed only when every possibility maps to zero (e.g. nothing can be Waiting before a queue row exists). Say so in the handoff: that is a logical bound, not an observation.
- Do not re-implement counts in the other language. The Python job pipes rows to a Node CLI that imports the page's own module, so the snapshot and the tiles cannot drift. A parity test renders the real home HTML and compares tile numbers.
- Which runs count as weekly points is a rule, not a fact in the data. Write it down, print the skipped runs in the dry run, and make only the weekly entry point (`run.py --weekly`) write snapshots.
