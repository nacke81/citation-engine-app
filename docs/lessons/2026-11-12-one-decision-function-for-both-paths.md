# Lesson: a dry run and a write must call ONE decision function (t_baa09af1)

#97 fixed the dry-run prediction by copying the write path's rules into a second branch. The copy missed one input: a row already in needs-human. The dry run said "plain backoff, +2 days"; the write said "park again" and added a duplicate history entry. The lesson `a-dry-run-runs-the-same-rules` was right, but copying the rules is not running the same rules.

Rule: put the decision in one function that returns a verdict (`already-parked | not-due | park | backoff`). Dry run and write both call it and differ only in whether they call `record`. Test every verdict by running both paths and comparing the results, including the shape the live queue really holds (a row the normal candidate filter never hands to a write run, but a direct call can).

Also: a state the filter hides from the write path can still reach it by direct call; make that case a no-op rather than relying on the filter.
