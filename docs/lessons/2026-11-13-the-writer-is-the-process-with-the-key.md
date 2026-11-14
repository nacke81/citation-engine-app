# Lesson: let the process that holds the key do the write, gated on the status it can read (t_eae8e59f)

The agent proves a playbook by doing the work, but it must not hold the DB key. The bridge-side run already holds the access and already watches the request to its end, so the write belongs there, after the oneshot is dead, gated on the portal status reading `verified` (the helper's accepted result), not on anything the agent says.

Rules that came out of it:
- Gate a write on a status the writer reads itself. Rejected, failed, superseded and unknown fall out of that one line; test each, and add a mutation that removes the gate and shows a rejected run then writes.
- Keep the agent's free text out of storage by default. Its stdout is read by a thread that keeps only the `PLAYBOOK-NOTE:` line; the note then passes the same text rules as a step (no 6+ digit run, email, code assignment) or is dropped.
- A "keep what is proven" rule needs the stored row's own proof marker (`last_proven_at`), and a mutation showing a short trace then clobbers it.
- A write-back failure must never change the run's result or log exception text (it can carry the code).
- Put a note in an existing text column (`source`) before adding a migration; the app already shows it.
