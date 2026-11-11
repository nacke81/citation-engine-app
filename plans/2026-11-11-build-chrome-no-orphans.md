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

## Round 2 (review comment 3770, written BEFORE the edits; cites docs/lessons/2026-11-11-a-child-you-kill-does-not-end-its-parent.md)
Lesson: a process's life is decided by its own handle, not by a shared port. Same here: "alive" must come from the thing we own.
1. Liveness = the owned Chrome process. `main()` passes `alive=` built from `oc.proc.poll() is None` AND the Job Object ActiveProcesses > 0 (new `OwnedChrome.job_active()`, QueryInformationJobObject class 1). CDP is no longer the signal in `main()`.
2. Refuse to start when CDP already answers (a second chrome hands off and exits): print `chrome_already_running=1 listener=<pids>`, write no pidfile, exit 4, before any window_count/launch.
3. `--stop` and `reap` kill the pidfile pid only if `list_procs` shows it alive with a build_chrome.py command line and a start time within 120 s of the pidfile `started`; else print `pidfile stale (pid N is not build_chrome.py)` and only remove the file. Same check for the reap lease/pidfile guard.
4. Tests: CDP answers but own proc gone -> chrome_gone; CDP misses but proc alive -> no exit; occupied port -> refuse, no pidfile; stale pidfile pid now `python other.py` -> no taskkill, file removed.
