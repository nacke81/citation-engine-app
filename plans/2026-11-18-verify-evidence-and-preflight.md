# Plan: Verify runs save evidence and stop at once on a signed-out session (t_761c9558)

Cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md` (latest at start): the agent's quoted page text and the real page must agree, so the helper reads the page itself (CDP, read-only) and the evidence on disk comes from that read, not from the agent's words.

## Base
origin/main 3697684. Worktree app-t_761c9558, branch feat/verify-evidence-t_761c9558.

## Change
1. `job/verify_evidence.py` (new): `read_page(cdp, domains)` (read-only CDP: url, visible text, screenshot, password-field flag, challenge-frame flag; None when unreadable or CE_NO_CDP), `classify(page, signup)` -> captcha | signed_out | signed_in (pure), `save(rid, label, page)` -> logs/verify-evidence/<rid>/NN-<label>.png + .txt (text redacted: 6+ digit runs, emails), linked in the stage file.
2. Scoreboard (`verify_scoreboard.py`): stage-file `evidence` map and `reason`; the finalized row gets `evidence` (relative paths), the specific `reason` as the outcome suffix (failed:session_signed_out), and `fence_skip: true` when the request never reached a send. Optional keys only, so existing rows keep their exact field set.
3. `verify_step.py`:
   - `FAIL_REASONS` adds session_signed_out, captcha (portal code signin_failed; the portal enum is not ours to change) and send_unconfirmed (portal code send_failed).
   - `stage --name signed_in`: pre-flight read. captcha or signed out -> evidence saved, request finished needs-human, exit 5, signed_in_at stays null. Unreadable page -> no stamp, no stop. Signup directories only get the captcha check.
   - `arm`: same captcha / signed-out check right before the click (never stamps signed_in_at).
   - new `watch`: run right after the send click. Stamps send_clicked_at (also for a CDP click), saves the after_send evidence at once, polls the page up to 40 s. Code box -> exit 0 (then `sent`). Still "Loading" with no code box at 40 s -> `send_unconfirmed` finish, evidence kept, exit 5, never retry.
   - sign-in evidence is saved on `stage signed_in`; end evidence is saved in `VerifyRpc.finish` (every run ends there) before the scoreboard row is written.
4. `verify_send.py`: prompt tells the agent to run `watch` right after the click and to treat exit 5 as stop; stage file records `signup` so the pre-flight knows when sign-in is not expected.
5. Thumbtack playbook v4 step 3 (seed + v4): signed in, Next opens the SMS consent panel, its Continue is the send.
6. Tests by execution with a mock page (`tests/verify_evidence_test.py`), added to CI.

## Not changed / coordination
The portal client text ("we need to sign in again") and the fence's counting live in nacke-platform. This card writes `fence_skip` on the scoreboard row and uses portal code signin_failed; the platform card must read those. Card t_e4f97eb5 is not visible from this board, so the column name is a proposal, flagged in the handoff.
