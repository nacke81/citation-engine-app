# Plan: Verify Now speed, Thumbtack phone check, queued click, and a send that must prove it landed (t_4ee21e60)

Cites lesson `docs/lessons/2026-11-15-a-kill-must-reach-the-process-that-acts.md` (latest): the irreversible step needs its own check right where it happens; do not trust a start-up check or a click that "worked". Here: `sent` is recorded only with page evidence the text went out.

## Measured (live, 11/15, this machine; stage stamps + bridge log + timed helpers)
- Alignable 53b9cd5e: pickup 00:43:03 -> started by the pass at 00:46:02 (deferred 3 passes behind Thumbtack, whose run ended 00:45:33: lock release was fine, gap 29 s = next 60 s pass) -> agent_start 00:48:32. **Pass-start -> agent_start = 150 s, all pre-agent setup.**
- Timed the setup steps on the real vault (read-only): `vault_lookup` 59 s + `login_username` 72 s (each logs in, unlocks and syncs Bitwarden; `--lookup-only` runs the same `readItem` that `login_username` runs, so the lookup is redundant) = 131 s. `hermes` CLI start = 8 s each (connect, session cancel). Agent cold start (start -> ready) 29-33 s. Bridge pickup 32-45 s (the 60 s Task Scheduler tick).
- Scoreboard before (`verify_scoreboard.py --summary`): 2 runs, median pickup 38 s, median pickup->start 143 s, median cold 30 s, pickup+start (requested->agent_ready) 212 s.

## Changes (job/ only, no portal write, no deploy)
1. **Phone check** (`playbook.py`, `verify_send.py`): step key `phone_on_account` (true only) + optional `phone_evidence` text. When the playbook marks any step, prompt step 2 = "This page shows no phone; the playbook records the code goes to the phone on the account. Proceed." Otherwise the strict check text is unchanged. Repo seed `config/playbooks/thumbtack.com.verify.json` = v3 content + the flag (v4). Prod set is a post-merge card.
2. **Cold start** (`verify_send.py`, `verify_bridge.py`, `verify_bridge.cmd`):
   a. Drop the redundant `vault_lookup` (login_username fails closed on the same read).
   b. Run `login_username` in a worker thread in parallel with the sitegate reservation, the playbook read, and Chrome start (`agent_browser`); join before the playbook renders. Same fail-closed codes.
   c. Bridge pass loop: `verify_bridge.py --loop-s 55 --every-s 15` inside the 60 s task tick (IgnoreNew drops overlap), so pickup <= 15 s and a deferred row retries every 15 s.
   Expected pickup->agent_ready: pass wait <=15 s + max(vault 72 s, Chrome/connect) ... the vault read is the floor (72 s) unless it overlaps the agent's own start. So (d):
   d. The agent's `{login_email}` comes from the pinned `EXPECTED_LOGIN[biz]` (the run already refuses any other vault username), so the agent starts at once and the vault identity check runs beside it. The check gets a hard gate: `verify_step.py arm` refuses unless the run wrote `vault-ok-<id>` (same lock dir as the started marker); a failed check kills the agent and ends signin_failed. Nothing is sent before the gate.
3. **Queue**: the tenant lock already frees when the run ends (measured 29 s to the next pass). With 15 s passes the gap is <=15 s. The queued row keeps its own arm window (requested_at based, START_LIMIT_MS unchanged: 540 s arm, 600 s sweep). No re-stamp needed; no limit moves.
4. **False sent** (Nate add-on, top priority): `verify_step.py sent` requires `--evidence "<short page text>"` (1-300 chars, no 6+ digit run/email/phone; refused otherwise) and refuses when the evidence reads as an error (`not a mobile`, `invalid`, `error`, `couldn't`, `unable`, `try again`) or has no landed signal (`code`/`sent`/`enter`/`text`). New `verify_step.py fail --reason directory_refused_phone|send_failed --evidence "<page text>"`: stores the page text in the stage file (`set_note`-style, `refusal_text`), finishes the request `failed/send_failed`, scoreboard row. Prompt: after the send click, read the page; confirm a code box or "code sent" text and no error near the phone field; then `sent --evidence`; any error -> `fail`.

## Tests (offline, no network, no send)
tests/verify_speed_test.py (+ CI step, + `--mutations`): both prompt variants + mutation (flag ignored -> strict stays); step key validation; vault_lookup not called + parallel login (fake runtime records overlap); vault failure kills the agent and ends signin_failed; gate refuses arm before vault-ok; loop runs N passes with a fake clock; sent refuses no/err evidence, fail writes failed + page text; mutations for each.
Existing suites rerun: verify_bridge/agent/kill_fence/scoreboard/browser/send_dry_run, playbook tests.
Lesson at the end.

## Outcome (as built)
All four items built as planned. Deviations: the Thumbtack v4 seed is a NEW file `config/playbooks/thumbtack.com.verify.v4.json` (the old signup seed is still pinned by tests/playbook_test.py); `sent` treats an agent's own "no error" phrase as clean; the vault gate waits up to 120 s inside `arm`. Add-on 5(c) (call code arrives as a recording URL): no transcription built. Add-on 5(a) readback: prod row a25e00ff (alignable.com) shows verification_type=sms, state=requires_verification, NOT phone-call.
Lesson: docs/lessons/2026-11-15-a-click-is-not-a-send.md
