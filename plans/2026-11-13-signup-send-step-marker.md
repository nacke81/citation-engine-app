# Plan: signup-path steps 2-4 name the playbook's send step, not "the Sign up click" (t_3223ee18)

Cites lesson `docs/lessons/2026-11-13-the-writer-is-the-process-with-the-key.md` (latest by mtime): one record, one owner of the fact. Here the playbook owns which step is the send; the generic prompt must read it, not assume it.

Problem: Alignable step 3 clicks "Sign Up It's Free" (no send); step 5 "Verify with SMS/Text" is the send. Generic step 2 says "before the signup click, check the phone" and step 4 says "The Sign up click already sent the code. Do NOT click any other send..." The agent reads that as a ban on step 5.

## Decision
Marker = a `send: true` boolean on the step (not text sniffing). `validate_steps` accepts it. `send_step_number(steps, send_is_signup)`: signup requires EXACTLY one marked step; non-signup allows none. `set_playbook` and `set --dry-run` refuse otherwise. `render` passes the boolean through. `build_prompt` (signup path) calls it and names step N in steps 2, 3, 4; it never says "Sign up click". A stored signup row with no mark fails the run before the agent (send_failed), fail closed.
`playbook_proven.write_proven`: a trace has no mark, so it must not overwrite a signup playbook's steps (it would be refused anyway); it keeps the steps and touches last_proven_at.

## Build
1. job/playbook.py: STEP_KEYS+send, send_step_number, checks in set_playbook/CLI, render passthrough.
2. job/verify_send.py: STEP3_SIGNIN constant, signup step2/3/4 wording with N, check after render.
3. config/playbooks: thumbtack step 7, alignable step 5 get `"send": true`.
4. job/playbook_proven.py as above.
5. Prod: `playbook.py set` both (v2), show back; print dry-run prompts for rows 61ccf904 and a25e00ff.

## Tests (tests/playbook_test.py)
- zero marks, two marks, mark with send_is_signup false, non-boolean: refused; exactly one: ok.
- Thumbtack prompt names step 7, Alignable step 5, in steps 2, 3, 4; no "Sign up click" text in the Alignable prompt.
- Existing section 9/10 checks updated to the new lines.
- MUTATIONS: validator that skips the count; prompt builder hardcoding "Sign up click"; marker on the wrong step.
- Full CI list.
