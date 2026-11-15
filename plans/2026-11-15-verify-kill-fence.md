# Plan: Verify Now - kill really stops the agent, pre-send fence, env + vault org reach the agent (t_c6eee3cb)

Cites lesson `docs/lessons/2026-11-14-a-tool-takes-its-client-from-the-data.md` (latest): take the client from the data, never a default. Here the vault organization comes from `TENANTS`, not from whatever org the agent last searched.

Found (request f2dbd5c0): `hermes chat --oneshot` is only a client of the profile's gateway (`gateway_chat.run_gateway_chat`, "no local fallback"). Killing the process tree drops the ws; the gateway turn keeps running and clicked the send after the bridge swept the request. The client env (BROWSER_CDP_URL, TERMINAL_CWD) travels only as `client_env`, which the gateway filters by the profile's `terminal.client_env_passthrough` (names not listed are dropped). The prompt named the vault item but not the organization.

Scope (job/verify_send.py, job/verify_step.py, new job/gateway_cancel.py, tests, CI, lesson):
1. Kill = stop. No in-process oneshot exists in this hermes build, so the kill cancels the gateway session: launch_agent keeps the child's stderr, reads the `Session: <id>` line, and AgentProc.kill() runs `job/gateway_cancel.py <id>` (hermes venv python: session.resume, session.interrupt, session.close) before the taskkill. Idempotent; a missing id is logged. The pre-send fence (3) is the hard stop for any case the cancel misses.
2. Env. launch_agent already puts BROWSER_CDP_URL/TERMINAL_CWD in the child env; the gateway only forwards names the profile allowlists. Add `agent_env_gap()` (reads the submitter profile config) and log a loud line per run when BROWSER_CDP_URL or TERMINAL_CWD is not in `client_env_passthrough`. The profile edit itself is not mine (no profile/config changes): follow-up card. The prompt also states the tenant browser, as before.
3. Fence: `verify_step.py arm --request-id X`. Exit 0 only when the request is `starting`, passes bridge.fence(), and age < SWEEP_AFTER_S - ARM_MARGIN_S (60). Otherwise exit 5 (swept row: 5). Prompt: the line right before the send click runs `arm`; nonzero = STOP, no click.
4. Prompt: names `organization` from TENANTS; every vault fill call carries `--organization "<org>" --collection Citations --name "<item>"`; hard rule: never create or edit a vault item in a verify run; item not found = stop.
5. Re-measure with a dry run on a virtual clock using the measured stage times from f2dbd5c0 minus the known losses (3 min own Chromium, ~5 min vault hunting) and report the number; SWEEP_AFTER_S changes only with evidence.
Tests (offline, tests/verify_agent_test.py + new tests/verify_kill_fence_test.py): kill during a fake run cancels the session and no further tool call executes; env reaches argv/env and gap detection; arm on starting/fresh = 0, swept row = 5, requested/code_sent = 5; prompt has org + rule + arm line; mutation checks on each fix. No network, no real send.

## Add-on (operator note, same card)
6a. Liveness sweep: every helper verb that passes the request check touches verify-stages/<id>.alive; stale_requests keeps a starting row past 600 s while the agent was heard from within 120 s, up to SWEEP_HARD_CAP_S = 900 (real unfixed click 789 s, fixed estimate ~309 s). arm's limit follows the hard cap (840 s).
6b. late_sent: step_sent on a could_not_start row, requested <= 1200 s ago, fence ok, no newer request for the verification row -> one conditional PATCH back to starting, then mark_code_sent. Assumes the portal allows the service role that PATCH (fails closed if not).
7. Copy fix lives in the portal repo: not this card (no grant); follow-up card.
8. Time to send: reported as arithmetic on the measured stages (no in-process mode exists, no real send).
