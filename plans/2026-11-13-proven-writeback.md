# Plan 2026-11-13: the bridge proves the verify playbook after an accepted code (kanban t_eae8e59f, Part B)

Cites lesson `docs/lessons/2026-11-13-one-source-for-the-steps.md`: one record for what the agent runs and what Mike reviews; placeholders, validated at write time; a refusal test needs a mutation that shows the unsafe path then happens.

## Where the write lives
The agent has no DB key. `verify_send.py` (started by the bridge, holds the Directory DB access) already watches the request to its end. In `_agent_send`, after the oneshot is gone and the portal status reads `verified` (the helper's `result --outcome accepted` set the row live and finished the request), the bridge-side runtime calls `write_back(request_id, domain, note)`. Rejected = `failed/code_rejected`, failed, superseded, unknown never reach it. The write never changes the run's outcome (any error is logged by type and swallowed).

## What it writes (new `job/playbook_proven.py`, shares `playbook.steps_from_trace` + `set_playbook`)
- Reads the PR #107 promote trace `verify-traces/promote/<domain>__<channel>__<request_id>.json` (already value-free, query/fragment stripped). Domain and request id in the file must match the run.
- Non-empty, valid trace: `verify` playbook = trace steps, `last_proven_at` = now, `source` = `request <id>` (+ note), version bumped (set_playbook), `send_is_signup` and the `stale` flag carried/cleared.
- Empty or missing trace, or fewer steps than an existing PROVEN playbook: keep the old steps, PATCH only `last_proven_at` (and clear stale, source). No version bump, steps untouched.
- A trace that fails `validate_steps` (6+ digit selector, email, code assignment): refused, nothing written.
- PLAYBOOK-NOTE: the oneshot's stdout is now read by a thread that keeps ONLY the last `PLAYBOOK-NOTE:` line (everything else is dropped in memory, never written, so a code in the agent's output never lands on disk). The note is validated like step text, cut to 200 chars, and stored as `; note: ...` in the row's `source` column (no migration: the app already shows Source). Never a step.

## Unchanged
Fence, 3-send cap, tenant lock, sitegate, the helper commands.

## Tests (red first)
`tests/playbook_proven_test.py`: accepted writes (steps, last_proven_at, source, version bump, signup flag kept); rejected writes nothing through the real `S.run`; superseded/failed none; code-like trace refused; empty and shorter trace keep old steps; note stored in source, not steps; note reader keeps one line only; MUTATIONS: (1) no `validate_steps` in the trace path then a 6-digit selector IS written, (2) drop the status gate then a rejected run DOES write, (3) drop the shorter-trace guard then proven steps ARE clobbered. Added to CI.
