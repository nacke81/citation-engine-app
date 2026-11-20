# Lesson: when two writers record the same fact, the quieter one is the bug (t_2211682c)

`transitions.py` and `nm_transitions.py` both move a queue row to live. Only the first touched the portal. A worker used the second, nm-create-alignable went live, the Your turn row (a25e00ff) stayed open, no Activities row was written, and the exit code was 0.

Rules:
- A writer that is deliberately queue-only must still report what it did not do, or hand the portal half to the shared helper. `queue_move_effects` is that helper now; the CLI and the build path call it.
- A PATCH that can match nothing must say how many rows it changed (`return=representation`). "No error" is not "done". 0 closed while a matching open row exists is an error naming the step.
- A caught exception that only goes to `errors` is invisible unless the CLI turns it into a non-zero exit and names the step on stderr. Test the CLI entrypoint with a failing fake, not only the function.
- A row the page filters out (approved_at NULL) is as missing as an unwritten one: assert the field the reader filters on.
- Do not infer "verified by code" from "state=live": a row closed by hand looks the same. Take it from the record that proves it (a code request finished 'verified'), never from a tuple of names: a tuple cannot recover the next verify.
- A same-state move is a note refresh, not news. Every writer that posts a client row must check old != new, in one shared helper (`is_client_news`), or a weekly recheck re-dates the client's history (merge-duplicates).
- A comment that promises a recovery path ("the backfill re-posts") is a claim: test that the path exists.
- A directory that cannot do a channel (Alignable refuses VoIP) is data, not a code tuple: `config/directory_flags.json`.
