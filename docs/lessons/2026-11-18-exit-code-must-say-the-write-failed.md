# Lesson: a CLI that reports a failure only in its JSON exits 0 and the caller never sees it

`--record-existing` returned 0 when the queue write succeeded but the client-row post failed (errors only in the printed JSON). A script or scheduler reads the exit code, not the JSON, so the missing client row looked like success.

Rule: when a command does a primary write and a follow-up write, a follow-up failure is a nonzero exit plus the exact retry command on stderr, while the primary write stays. Test it through `main()` with a raising fake and a mutation that restores `return 0`.
