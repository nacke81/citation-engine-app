# Plan: weekly job runs the fill (t_c3087efc follow-up)

Builds on plans/2026-11-04-fill-reason-codes.md. Hard guard from t_93ae9b6b round 2 stands.
Nate ruling (2026-11-04 13:42): weekly job calls the fill with write AFTER sync_run; live fill pre-approved (fill-only, never overwrite, never null).

- job/run.py directories_step: after sync_run, if a queue exists, call D.fill_reason_codes(write=True). Non-fatal. queue_rows_to_status untouched.
- tests/weekly_fill_test.py: order (fill after sync), one-column filtered PATCH, failure non-fatal, no queue means no fill.
- CI: add fill_reason_codes_test and weekly_fill_test.

Note: this plan file was written after the code edit in this run (process slip, disclosed in handoff).
