# Plan: Verify Now send run must not open a visible console (t_58ea23a5)

Cites lesson `docs/lessons/2026-11-18-a-zero-needs-a-reason-it-could-see.md` (latest at start): prove "no window" by reading real window state, not by assuming.

## Finding (base 4145673)
The scheduled task already starts the bridge hidden (wscript //B hidden-run.vbs -> verify_bridge.cmd). The blank window comes one level down: `verify_bridge.start_send` launches `verify_send.py` with DETACHED_PROCESS, so that process has no console. Each console-subsystem child it starts (hermes agent oneshot, node, taskkill) then allocates its own new visible console. The agent run lasts 5-10 min = the window Mike sees.

## Change (no logic or timing change)
1. verify_bridge.py: `NO_WINDOW_FLAGS` = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW replaces DETACHED_PROCESS in start_send. Log redirection unchanged (verify-send-<id>.log).
2. verify_send.py launch_agent Popen: add CREATE_NO_WINDOW.
3. Test: spawner fake sees the flags (has 0x08000000, lacks 0x8, log stream still passed); plus a real-window probe run by hand on this PC.

Note: plan committed after the edit began; recorded in the card.
