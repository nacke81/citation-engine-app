# Plan 2026-11-13: the agent's playbook note goes through the helper, not stdout (kanban t_eae8e59f, Nate round 2 on PR #113)

Cites lesson `docs/lessons/2026-11-13-the-writer-is-the-process-with-the-key.md`: the writer of a shared record is the process that holds the key; the agent passes evidence through a narrow, validated channel.

## Change requested
Nate: do not pipe the oneshot's stdout (a reader thread is a new hang/EPIPE path on Mike's live send run). Stdout goes back to DEVNULL. The agent reports its note with `verify_step.py note --request-id R --text "..."` instead of printing `PLAYBOOK-NOTE`.

## Design
- `verify_step.py note`: allowed only while the request is `starting`, `code_sent` or `checking` (same fence as the other subcommands); max 400 chars; refuses (exit 5, nothing stored, no text logged) 6+ digit runs, emails, phones, code/password assignments (same `playbook._check_text` rules as steps); empty or over-long text refused. `ok` is accepted and means "no change".
- Storage: `verify_scoreboard.set_note/take_note`, key `playbook_note` in the request's stage file (last write wins). `finalize` used to delete the stage file before the bridge's write-back runs, so on a `verified` outcome it now leaves a stub `{_finalized, playbook_note}` (only when a note exists) and `finalize`/`stamp` ignore a finalized file; `take_note` reads and deletes it. Other outcomes delete as before.
- `verify_send`: `NoteReader` and the PIPE are removed; `launch_agent` uses `stdout=DEVNULL` again; `AgentProc.note` is gone; `write_back` takes the note from `SB.take_note(request_id)`, then `playbook_proven.write_proven` as before (re-validated, 200 chars, stored in `source`, never a step).
- Prompt step 8 tells the agent to run the `note` command (never print it) and says it only matters on accepted results.
- Unchanged: playbook_proven.py, the `verified` gate, shorter-trace keeps steps, refused traces write nothing, fence, 3-send cap, tenant lock.

## Tests (red first)
`tests/playbook_proven_test.py`: note CLI stores in stage file; refuses 6-digit run, email, phone, over 400, empty, wrong state (`requested`/`verified`), bad id; note survives `finalize` verified and is gone after take; rejected run's stage file leaves no note; prompt contains the `note` command and no `PLAYBOOK-NOTE`; stdout is DEVNULL; accepted run through `S.run` stores the note from the stage file in source. MUTATION: drop the validator in `step_note` then a 6-digit note IS stored. Existing 28 still pass (NoteReader tests replaced by these); `verify_agent_test` stdout assertion reverts to DEVNULL.
