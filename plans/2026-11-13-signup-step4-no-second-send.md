# Plan: PR #110 round 3, step 4 must not ask for a second send on the signup path (t_f683311e)

Cites lesson `docs/lessons/2026-11-13-one-source-for-the-steps.md` (latest): the agent must get one unambiguous instruction per fact. Today step 3 clicks Sign up (= the send), then step 4 says "Choose the sms option and send the code". An agent may hunt for a second send or a Resend link, which kills the first code.

## Build
1. `job/verify_send.py`: `step4` is path-aware. Signup (playbook send_is_signup true): "4. The Sign up click already sent the code. Do NOT click any other send, resend or SMS option. Immediately run: <helper> sent ...". Sign-in path keeps today's step 4 unchanged.
2. Fence, tenant lock untouched.

## Tests (playbook_test section 10)
- Signup prompts (Thumbtack, Alignable): exact step 4 line present; no "send the code" / "Choose the" text after the step 3 line.
- Sign-in prompts (playbook without flag, no playbook): today's step 4 line still present.
- MUTATION: swap the signup step 4 for the generic one, check fails. MUTATION: a "resend" order added, check fails.
- Full CI list; re-print Thumbtack 61ccf904 dry-run prompt, attach.
