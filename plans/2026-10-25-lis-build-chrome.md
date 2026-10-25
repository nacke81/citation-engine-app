# Plan 2026-10-25: real Chrome for Lis, signup URLs, verify_type in history (kanban t_568f1ee6)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-25-buildrows.md. Applied from it: stdlib only, no schema change, tests set CE_QUEUE/CE_RUNS to temp before import, base origin/main ebaaf99, atomic write with .bak before any queue edit.

## Findings before code
- Portal verification queue DID get the ezlocal sms entry (prod `citation_verification`: ezlocal.com / sms / requires_verification, parked 2026-10-25T18:29Z). Only the queue-row history is wrong: `record_transition` builds the history entry without `verify_type`, so it is `None` when read as a field (the type lives only in the note text). Fix: write `verify_type` into the history entry when set. No portal/approval-rule change.
- Submitter attaches to a browser by `BROWSER_CDP_URL` (profile .env) or `browser.cdp_url` (config.yaml), or `/browser connect`. A static value needs a fixed port.

## Design
1. `OwnedChrome(profile=None, port=None, persistent=False)`: backwards compatible. persistent => use the given dir, never delete it on close. Default behaviour (throwaway profile, random port) unchanged.
2. `job/build_chrome.py`: starts OwnedChrome with the persistent profile `%LOCALAPPDATA%/citation-engine/build-profile` and fixed port 9333 (override `--port`), prints `cdp_url`, window count before/during, blocks until Ctrl+C / `--seconds N`, closes the tree via the Job Object, reports window count after. No Directory traffic itself.
3. `job/build_proof.py` (proof run only, read-only): through that Chrome via CDP, load homepage + search of 6 Directories, classify loads/challenge/403, screenshot. No click on forms, no submit.
4. Queue data: one-off script with .bak first; sets only `signup_url`/`claim_url` on 4 rows. state/history/approval untouched; test asserts that on a copy.
5. verify_type: history entry carries `verify_type`; test added to transitions_test.py.

## Verify
Full local suite, CI on PR. Proof run: per-site result + screenshots, window count before = after.
