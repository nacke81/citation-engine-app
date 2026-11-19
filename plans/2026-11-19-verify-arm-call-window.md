# Plan: Verify Now phone-call requests arm/disarm the NM line; call_code reports only inside an armed window; Functions in the repo (t_282b646e)

Cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md` (latest at start): a new source may fill a gap, never override a value that contradicts it. Here the local arm-window log is a new source for call_code. It may only NARROW what is reported (a recording whose call started outside every window prints nothing); it never turns a no-code transcript into a code. Both cases (inside the window, outside it) are tested in the same file.

## Facts (read-only, 2026-11-19)
- PR #145 merged (dff9159). Function side live: Serverless service `nm-public-line`, prod build ZBb10dc3d3510b7d08e86eb88d20b33da2, 5 Functions (/voice /voicemail /vm-done /after-dial /sms). /voice reads Sync doc `verify_armed` (service from Service env `ARM_SYNC_SID`); armed iff now < verify_armed_until AND now < date_updated + 15 min; any error/2 s -> forward.
- The live /voice source carries the line number in a header comment. leak_check decides whether that can sit in the repo byte for byte (checked in item 3).

## Item 1: `job/verify_arm.py` (new) + hooks
- `SyncArm`: `arm(request_id)` POSTs Documents (UniqueName verify_armed, Data {"verify_armed_until": now+12 min ISO UTC}, Ttl 900), on 409 POSTs Documents/verify_armed; `disarm(request_id)` DELETEs Documents/verify_armed (404 = already gone = ok). Never raises, never logs creds or URLs with creds, 5 s timeout. Same creds file as call_code (`C:/Credentials/twilio-api.json`, env `CE_TWILIO_CREDENTIALS`). Env `CE_NO_TWILIO=1` makes every call a refusal (set by tests/verify_fakes.py).
- Window log (`%LOCALAPPDATA%/citation-engine/logs/verify-armed-windows.json`, env `CE_VERIFY_WINDOWS`): list of {request_id, start, until, end}. arm appends; disarm sets `end` only when the DELETE worked (a failed disarm leaves the window open to `until`, which is what the line really does). Holds no number, no code. Last 50 kept.
- `verify_send`: arm only when channel == phone-call AND tenant == NM (the NM line is not SCC's), right before the send step: agent path just before `launch_agent`, script path just before `click_send`. `run()` wraps `_send` in try/finally -> disarm (verified, failed, closed, superseded, unknown, claim lost, kill, exception). The Runtime owns `armer`; a runtime with no `armer` (every existing fake) never arms.
- `verify_bridge.sweep(..., armer=None)`: after a swept request finishes, disarm if the open window belongs to that request id (covers a send run killed hard so no finally ran). `main()` passes the real armer to the pass loop.
- A disarm/arm failure is logged (type only), never fatal.

## Item 2: call_code window gate (the structural fix for "gate pin is 4455")
- `recordings_since` also returns the call start (`started`); `run_once(..., windows)`: a recording with a code prints a line only if its call start is inside a window [start, end or until]; outside -> no line (seen, nothing printed). `--windows FILE` flag defaults to the same path. No regex edit.
- Missing/unreadable windows file = no windows = nothing printed (fail quiet; the inbound voicemail cron still reports voicemails).

## Item 3: cron
- `no_agent` cron in the NM profile (the Hermes profile named in the card), every 2 min, running `python job/call_code.py --since <registration time>` through a wrapper script in the profile `scripts/` dir (scheduler passes no args), box python with faster-whisper, delivery the way the nm-listings relay does. Dry-run of the exact command on REbe645b first (code length only). Registered only after the PR merges (the cron runs the runtime clone).

## Item 4: Functions in the repo
- `twilio/nm-public-line/<name>.js` for the 5 live Functions byte for byte; `.gitattributes` keeps LF. `twilio/deploy.py`: `--dry-run` (default) diffs repo vs live (Serverless API GET only), exit 1 on any diff; `--export` writes the live sources into the repo dir. No deploy verb.

## Tests (red first)
`tests/verify_arm_test.py`: arm on phone-call NM; no arm on sms; no arm on SCC phone-call; arm before launch; disarm on verified / failed / closed / superseded / exception / kill; arm failure not fatal; disarm failure logged not fatal; sweep disarms own request only; REST shapes (POST/409/DELETE bodies) through a fake transport; no creds in logs; mutations: drop the disarm; arm for sms. `tests/call_code_test.py`: in window prints, outside prints nothing, no windows file prints nothing, contradiction (no-cue text inside the window prints nothing). `tests/twilio_functions_test.py`: dry-run 0 diff with a fake transport, a changed byte is reported, no write verb in deploy.py. leak_check must pass.

## Proof (after merge; nothing sent to a Directory)
arm with a dry-run request id, one test call to the line, recording seen, call_code Telegram line, disarm, second call rings Mike's cell. The test call and the arm are live Twilio actions: if I cannot place a call without a spend/approval gate, I stop and report it rather than skip it.
