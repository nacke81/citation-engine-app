# Plan: Verify Now agent send path (t_218b03ef)

Cites lesson `docs/lessons/2026-11-12-the-stuck-state-needs-its-own-owner.md`: every intermediate state needs a second owner with a clock. The agent path adds a new intermediate actor (an LLM oneshot that can hang or wander), so the send run owns it: a 25 min kill clock before `sent`, a post-send poll bound, and a final "the agent ended, the row did not" finish. The existing 10/40 min sweeps stay the backstop.

Scope:
1. `config/verify_directories.json` replaces `SMS_DIRECTORIES`: domain, aliases, channels (sms, phone-call), send (script|agent), signin_url, vault item per tenant. Cylex is `send=agent` for now (Nate stop: the scripted selectors were never confirmed on a signed-in session; flip to script only in a PR citing that run's saved pages). A directory not in the file, or without the request's channel: failed/no_playbook, 0 site loads. `fence()` stays the one decision.
2. `job/verify_step.py sent|code|result`: the only thing the agent calls. It owns mark_code_sent, consume_verify_code, the superseded check, set_verification_live, finish_code_request. The agent has no service key.
3. `job/verify_send.py`: no scripted send -> write a prompt file (no code in it), launch `hermes -p citation-submitter chat --query-file <f> --oneshot` through an injected runner, tenant lock held, one sitegate reserve. Kill the whole process tree at 25 min with no `sent` (failed/send_failed). After the agent exits, any non-closed row is finished with an allowlisted code.
4. Login email from the vault item's username (`job/vault_username.cjs`, prints the username only, never the password). Must equal the expected listings@ address per tenant, else failed/signin_failed. `CE_VERIFY_LOGIN_EMAIL_*` and identity.json removed.
5. NM relay window (cron `*/2 8-19`, Central): an NM send outside 08:00-19:58 CT fails `timeout` before any site load.
6. Carried stops: superseded only on a row that is present and no longer waiting (an empty read is a miss, 3 misses -> other); click-to-send seconds logged (requested -> claimed -> sent); lock acquire retries briefly so a bridge probe cannot defer a run.
7. `verify_bridge.py --check` (read-only list of portal sms/phone-call rows whose directory is not in the file).
8. Tests with a fake oneshot runner; leak test over helper + prompt file; stale "Open contract item" line removed from the prior plan.
Step 8 of the card (scheduled task) runs after merge, outside this branch.
No live send, no CapSolver, no portal write beyond tests.
