# A dry run must run every rule the write path runs, then stop before the write

Plan `plans/2026-11-12-dry-run-predicts-the-park.md` cites the earlier lesson `2026-11-11-two-readers-of-one-page-must-share-one-block.md`.

`_backoff()` returned on `not write` before the not-due and 3/3 cap checks, so a dry run said "submitted, due in 2 days" while the next `--backoff-only` parked the row. A dry-run flag that skips the decision rules only skips the write if you put the return after the rules, not before them. Put the early return for "do not write" at the last step, and test dry run against the real write on the same row at the edge of every threshold (2 of 3, 3 of 3, not due). A help string that says "no transition" is a claim: pin it with a test too.
