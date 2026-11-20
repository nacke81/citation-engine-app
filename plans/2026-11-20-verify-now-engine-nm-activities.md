# Plan: NM Activities on, live moves close the Your turn row (fail loud), mobile-only directories park self-serve (t_2211682c)

Cites lesson `docs/lessons/2026-11-19-gate-on-the-window-not-the-words.md` (latest at start): gate on the structural fact, not on more wording. Here the structural fact is "which writer ran": the row stayed open because the writer the worker called has no portal step at all.

## Root cause of t_d038172d (read from the worker's session log, read only)
The worker ran `python job/nm_transitions.py --row nm-create-alignable --to live ...` (a dry run, then the real write). `nm_transitions.py` is queue-only by its own docstring ("no portal, no Activities, no Local SEO"). It never calls `citation_verification`, so a25e00ff was never touched, no error was raised, and exit code was 0. The `out["errors"]` catch in `transitions.record_transition` was not even reached. Two defects: (1) the NM build/live writer has no portal step, (2) the portal step in `transitions.py` swallows a failure into `errors` and the PATCH never reports a row count.

## Items
1. `TENANTS["NM"]["activities"] = True` (transitions.py). `nm_transitions.record_transition` gains the portal step after the queue write (opt-in `side_effects=True`/`portal=`; CLI and `buildqueue.submit_row` for NM turn it on): one shared helper in transitions.py writes the Activities row (same writer, titles, approved_at, CE_ACTIVITIES_WRITE flag) and closes the verification row on live. Test: NM live plans exactly one deliverables row with the NM client id; swapping the tenant client id fails the test (mutation).
2. `set_verification_live` writes one Activities row `Verified your <dir> listing by phone code|text code` (source_ref `citation-transition:<verification-id>:verified`, same-day date). The write is best-effort after the PATCH succeeded (never undoes the live flip); failure goes to stderr.
3. `job/nm_activities_backfill.py`: dry run prints planned rows; `--write` POSTs through `P.write_deliverables` only; NM client id hard-wired; idempotent by source_ref (reads existing refs, plans 0 on the second run). Includes the Thumbtack verified row.
4. Fail loud: helper `close_verification_on_live` (PATCH return=representation, count rows closed; 0 closed while an open row for the same client + normalized directory exists = error naming ids). Every verification error is prefixed with its step (`verification upsert`, `verification retype`, `verification live PATCH`). CLI prints `FAILED STEP:` lines to stderr and exits 2. Test drives `main()` with a failing fake portal.
5. Mobile-only: data file `config/directory_flags.json` (`phone_verify_requires_mobile`), alignable.com true. A sms/phone-call park on such a directory is rewritten to id-check (steps: needs a mobile number, verify with your own cell; directory_url https) after the Your turn gate, so no Verify Now row and no allowlist add.

## Not done
No SCC writes, no flag change, no portal code, no prod write before merge.
