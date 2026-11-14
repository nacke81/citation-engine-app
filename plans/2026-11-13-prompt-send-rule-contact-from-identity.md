# Plan: PR #110 round 2, one clear "click send" rule; contact_name from identity.json (t_f683311e)

Cites lesson `docs/lessons/2026-11-13-one-source-for-the-steps.md` (latest): a value that matters lives in ONE place. contact_name was a code constant beside the identity file that already holds every other tenant value; it moves to that file.

## Build
1. `job/verify_send.py` prompt step 3 becomes: "3. Click the send button. Before you click it, if the page shows a paid upsell, a plan purchase, or a marketing consent that is not required for the code, do NOT click; end the session and report it." One line, shared by the signup and sign-in paths (no per-path copy). Fence, tenant lock, hard rules untouched.
2. Delete `CONTACT_NAME`. `Runtime.tenant_values` reads `BIZ[<tenant>].contact` from identity.json only. No key = no `contact_name` value = `PB.render` raises = `send_failed` before the agent launches (existing path, now tested end to end through `_agent_send`).
3. Runtime identity.json (outside the repo): add `BIZ.NM.contact` (backup first). SCC gets none, so an SCC run of a playbook that needs it fails closed.

## Tests
- playbook_test section 9: built prompt for the signup path and the sign-in path (a) contains the exact rule line, (b) every line mentioning "click send" is conditional, none says "do not click send" bare, (c) "STOP at the send step" is gone. MUTATION: restore the old line, the test must fail. 
- contact_name: tenant_values reads `contact` from a temp identity; no code constant (grep source for CONTACT_NAME = none); missing key -> `_agent_send` ends send_failed with no agent launch. MUTATION: reinstate a fallback constant, the missing-key test must fail.
- Full CI list, leak_check green, re-print the dry-run prompt for the real thumbtack verify row 61ccf904.
