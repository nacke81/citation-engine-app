# Lesson: a shared tool must take its client from the data it reads, not from a hard-coded default (t_5b3b4a3f)

mail_scan kept a fixed list of SCC directories, so NM directories (n49, techbehemoths) read as "0 mails" while the mail sat in the relay file. recheck compared every queue's phone to the SCC identity, so the NM queue was refused. Both looked like "no data" or "bad data" and sent the submitter hunting.

Rules:
- Derive the client from the rows (id prefix), refuse a file that mixes clients, and pass that client to every identity lookup, resolver and `record()` call. One hard-coded `"SCC"` left behind is a wrong-client write.
- A directory the tool does not know must say so, not report zero. When widening a list for one client, gate the widening on that client's mode and reset it after the run (try/finally), so the other client's behaviour stays byte-identical.
- Prove both clients in one test file and mutate the fix away: reverting each change must fail the NM checks while the SCC checks still pass.
