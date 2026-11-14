# Plan: every verify playbook marks exactly one send step; sign-in steps 3/4 name it (t_8b8c2650)

Cites lesson `docs/lessons/2026-11-13-one-source-for-the-steps.md` (latest): the agent gets one unambiguous instruction per fact, from one stored record. The sign-in prompt today says "3. Click the send button" and "4. Choose the sms option and send the code" while Alignable's step 5 is itself the one send click: two send orders, possible second SMS (found in t_fc4dc15d dry run a25e00ff).

Nate's decisions (card comment): permanent fix for both paths; stop on a CAPTCHA in verify runs.

## Build
1. `job/playbook.py`: `send_step_number` requires EXACTLY ONE `send: true` step for every verify playbook, whether or not send_is_signup. Drop the "marked but not signup" refusal. `set_playbook` and the CLI `set` check apply it for task verify only (other tasks never carry a mark; a mark on a non-verify task is refused). Writers that make unmarked verify steps (`playbook_proven` trace, backfill) skip/refuse rather than write an unmarked verify row (stored unmarked = fail closed at launch).
2. `job/verify_send.py`: when the playbook exists, n = send_step_number on BOTH paths. Step 3: "Do the send step (playbook step N) once. ..."; step 4: "Playbook step N already sent the code. Do NOT click any other send, resend or SMS option after it. Immediately run sent". The generic "Choose the <ch> option and send the code" line only remains with no playbook at all. Signup carve-out (account creation, CapSolver on NM) stays tied to send_is_signup. `_agent_send`: a stored playbook with no/2+ marks fails closed (send_failed) before launch on both paths.
3. `config/playbooks/alignable.com.verify.json`: becomes the live sign-in v3 (send_is_signup false, mark on step 5); step 3's CapSolver text replaced with "If a CAPTCHA shows, STOP and report needs-human (session expired)". Hard rule "No CapSolver" unchanged.

## Tests (tests/playbook_test.py)
- Render Thumbtack (signup) and Alignable (sign-in) prompts: exactly one send instruction each (one "send step (playbook step N)" order, no "Click the send button", no "Choose the ... send the code", step 4 never orders a click).
- Stored sign-in verify playbook with 0 or 2 marks: send_failed before launch; `set` refuses 0 and 2+.
- Alignable seed text has no CapSolver; says STOP on CAPTCHA; prompt still has "No CapSolver".
- MUTATIONS: generic step 3/4 back on the sign-in path; validator without exactly-one; CapSolver text back in the seed. Each caught.
- Full CI list.

## After merge (separate steps, Nate's item 3)
`playbook.py set` alignable v3 (send on step 5); re-set thumbtack only if the shape changed (it keeps its mark, step 7). Re-run both dry runs, attach to this card.
