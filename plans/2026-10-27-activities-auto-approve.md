# Plan 2026-10-27: routine citation Activities rows auto-approve (t_ac6e82a6)

Cites lesson docs/lessons/2026-10-27-read-the-whole-modal-before-blaming-the-password.md: keep behaviour behind its own flag instead of folding it into another one, so the hold path gets CE_ACTIVITIES_HOLD, separate from CE_ACTIVITIES_WRITE.

- activity_title: rejected becomes "<Domain> declined the listing" (first letter capitalized, no promise words).
- build_activity_record: approved_at = now (UTC ISO) for the four templated states; null when CE_ACTIVITIES_HOLD=1 or activities_hold=True.
- Header docstring updated, cites the 2026-10-14 ruling.
- tests/transitions_test.py: update T6/T7 approved_at asserts; add golden words test, approved_at non-null, HOLD=1 null.
- Dry run only; no prod writes.
