# Lesson: a safety rule that only holds on one path is not a rule (t_8b8c2650)

PR #114 fixed "a second send" for the signup path only, because the send mark was tied to `send_is_signup`. The sign-in path (Alignable) kept the generic "3. Click the send button" and "4. Choose the sms option and send the code" while the playbook's own last step was already the send click. A dry run of the real prompt caught it before Mike clicked.

Rules that came out of it:
- A fact the prompt names (which step sends) must be required of EVERY stored record of that kind, not only the one that triggered the first bug. The flag (`send_is_signup`) decides permissions (account creation, CapSolver); it must not decide whether the send is named.
- Fail closed in two places: the writer refuses 0 or 2+ marks, and the run refuses a stored playbook that has none before any prompt or browser exists.
- Machine writers (trace write-back, vault-note backfill) cannot name the send step. They must not create or replace a verify playbook; they stamp proof only, and the owner names the step (`from-trace --send-step N`).
- Test the rendered prompt by counting send ORDERS (one), not by matching one expected line; add a mutation that puts the generic line back.
- Two rules that conflict in one prompt (hard rule "No CapSolver" vs a playbook step that says use CapSolver) are resolved in the data, with a test that the stored text carries no solver wording.
