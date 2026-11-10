# Lesson: when the DB is the truth, the file readers use must carry it too (t_78dc54b5)

Cite: `plans/2026-11-10-mirror-proof-into-queue.md`.

The engine guard read ce_directory_status and was right, but two humans read the queue file and under-counted SCC Proof (10 of 38, true 22), because 12 live rows built before the Proof writer never got a `proof` key in the file.
Rule: a guard that has a "DB is the truth" fallback hides a stale file. Fix the file at every writer (there was no single shared one: transitions, buildrows, weekly_merge) and give a one-shot to repair history, instead of teaching each reader about the fallback.
Pins: a complete queue proof is never overwritten; sink off skips; a DB failure never blocks a queue write; the mutation checks (hook off, overwrite on) both fail the test.
Also: an existing test asserted "only the named row gets Proof" by reading every ce_directory_status call; the mirror's read-only GET broke it. Filter on verb, not on path.
