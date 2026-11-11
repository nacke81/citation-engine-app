# Plan 2026-11-11: build_chrome.py leaves no orphan pythons (t_15f7ec86)

Cites lesson `docs/lessons/2026-11-11-two-readers-of-one-page-must-share-one-block.md`: one function decides, every caller uses it. Here: one `hold()` loop owns "when does the build Chrome end", one `reap()` owns "which build_chrome.py trees die", and `stop()` calls both instead of carrying a third idea. (Plan was written alongside the code in one pass, not before the first edit; noted for the reviewer.)

## Cause (Nate, on disk)
`--seconds 0` -> `end=None` -> `should_close(None)` is always False and the loop never looks at its Chrome. `--stop` kills the CDP listener (Chrome), which is the CHILD of the python, so the python lives on.

## Changes (job/build_chrome.py)
1. `hold()`: every 5 s a CDP check; 2 misses in a row -> `chrome_gone=1`, fall through to `windows_after`.
2. `--seconds 0` -> `stop_at = start + CE_BUILD_MAX_SECONDS` (14400); `KA.should_close` already waits while a lease is fresh. `idle_cap_reached=1` printed.
3. pidfile `%LOCALAPPDATA%/citation-engine/build-chrome.pid` (`CE_BUILD_PIDFILE` override for tests): pid, port, started. Written on start, removed by its own python on exit; `--stop` taskkills its tree too and removes it.
4. `--reap [--older-than-minutes N=60]`: process list via PowerShell CIM (runner injected), roots = topmost `job/build_chrome.py` line without `--stop`/`--reap`, never self or own ancestors, age >= N, tree killed with `taskkill /PID n /T /F`. Trees holding the fresh-lease pid (or the pidfile pid while a lease is fresh) are skipped and counted `left`. Final `reaped=<n> left=<n>`, exit 0 only when left=0.
5. `--stop` ends with `reap(0, only_chrome_gone=port)`.
6. `owned_chrome` import made lazy so `--stop`/`--reap` and the tests run on Linux CI.

## Tests
New `tests/build_chrome_leak_test.py` (in CI, fake clock/runner/process list). Updated `tests/batch12_test.py` C1 (meaning of `--seconds 0`) and `tests/batch20_test.py` (fake runner answers the process list; pidfile/lease paths in temp).

## Not done here
No `--reap` or `taskkill` against the live machine (QA child t_ef792bca). Runtime clone and v1 repo untouched.
