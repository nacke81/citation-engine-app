# Plan: --reap never kills a tree whose Chrome is alive (t_fb7ae698)

Cites lesson `docs/lessons/2026-11-12-the-stuck-state-needs-its-own-owner.md` (latest): a cleanup actor needs its own liveness signal; here "age over 60 min" is not proof a batch is dead, so the reaper reads the owner's own signal (its Chrome) before it kills.

Scope (job/build_chrome.py only, plus tests/build_chrome_leak_test.py):
1. `reap()`: per candidate tree, read `--port N` / `--port=N` from the tree's build_chrome command lines (default 9333). Skip when a process in the tree has `--remote-debugging-port=<port>` or the port answers CDP (`port_alive`, injectable). Print `skip tree N: chrome alive on <port>`; counts as left. Chrome-less trees over the age limit are still reaped. The 4 h idle cap in `hold()` is untouched.
2. `_tk` returns the kill rc; reap re-lists processes and counts a tree reaped only if its root is gone (an empty re-list is unverifiable = not gone). Otherwise left += 1, rc 1.
3. `stop()` passes `only_port=port` so its reap touches only trees on --port.
4. `GONE_AFTER_MISSES` comment: owned proc/job signal, not CDP checks.
Tests: two trees >60 min (9333 chrome gone, 9444 chrome alive) -> only 9333 killed; failing kill -> rc 1; --stop leaves other-port trees; mutation (alive check removed) must fail the test.
No live --reap or kill on the machine; all offline fakes.
