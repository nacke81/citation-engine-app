# Plan 2026-10-26: hard-block retry cap in code (kanban t_fccbb7ef)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-26-recheck-signed-out.md.

Rule (Mike 10/26): "Sorry, you have been blocked" (Cloudflare 403 + Ray ID) = 1 try per calendar day, 3 tries, then STOPPED until Mike resets it.

1. `job/walls.py` (new, stdlib only). A try is a history entry `{wall: "hard-block", try: N, at, ray_id, note}`. Tries count since the last reset entry.
   `check_try(row, today)` refuses a stopped row, a 2nd try on the same day, a 4th try. `record_try(...)` calls it, appends the entry; try 3 also sets state needs-human and note `WALL:hard-block STOPPED, waiting on Mike`.
   `reset_wall(row)` appends `{wall: "hard-block", reset: true}`; only the CLI `--reset-wall <row>` calls it.
   `gate(queue, directory, today)` returns a refusal text or None, for runners.
2. `build_runner.main`: gate before connecting to Chrome (dry and live); skip with a log line, exit 0. A live run whose failed step reads "you have been blocked" is flagged in output with the exact `walls.py --record-try` command (the runner never writes the queue itself).
3. `transitions.record_transition`: a stopped row refuses every move except a needs-human note refresh.
4. `site/builder.js`: a needsPerson row whose note starts `WALL:hard-block STOPPED` shows "Blocked 3 days, stopped. Mike to look." (queue_note already flows from the last history note via directories.py; no migration.)
5. Tests: tests/walls_test.py (same-day, 4th, stop note, reset, gate, runner skip, transitions guard) and tests/builder.test.mjs (site label). walls_test added to CI.
No live queue writes in this card.
