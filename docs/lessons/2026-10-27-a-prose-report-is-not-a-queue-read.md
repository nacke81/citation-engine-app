# Lesson 2026-10-27: a worker's prose is not a queue read

Batch 21 told us "recheck_due set on bbb, loc8nearme, businessyab" and listed the rows still workable by hand. The queue said dnb and discoverourtown had no date at all: the `--backoff-only` run printed `no-permalink` for them, wrote nothing, and nobody could tell from the output. Two rows would have stayed submitted for ever, and the "workable" list was whatever the worker remembered.

Rules:
- A command that is meant to move a date prints `old -> new` and reads the file back to say it landed. "Ran without error" is not "wrote".
- Every row a batch tool reads ends with a state, a date, or a stop. A path that falls out of the loop with `continue` and no write is a bug, not a verdict.
- A cap needs a counter in a structured field (`backoff: no-permalink` on the history entry), never a count of prose notes. A test with four prose notes proves the prose does not count.
- What the next batch may touch is computed from the queue by a script and pasted in the handoff, not written by the worker.
