# Lesson: a rule about every write path needs one writer and a scan, not a convention (t_25000cbd)

PR #49 made the routine transition auto-approve, but the rule lived inside one builder, with an opt-out flag beside it. A retry, backfill or new transition type could have copied the inline POST and landed `approved_at` null, hidden from the client feed with no error.

Rule: put the invariant (source, approved_at) in the single function that builds the row AND the single function that posts it; then scan every non-test file for the table name outside that file. The scan must be proven with planted writers (python, SQL, JS) and the helper with mutants (approved_at dropped, source dropped, caller value kept), or it can pass while seeing nothing. Remove opt-outs that recreate the bad state (the CE_ACTIVITIES_HOLD path).
