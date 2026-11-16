# Plan: re-park must retype a waiting verification row; ERROR_TEXT must not trip on the resend link (t_5148d0b9)

Cites lesson `docs/lessons/2026-11-15-a-click-is-not-a-send.md` (latest): a recorded step must be backed by what actually happened. Here: a park that "succeeds" but leaves the row at the old type is a false success; read it back.

## Cause (read from code + prod readback)
`transitions.record_transition` step 3b upserts `citation_verification` with `resolution=ignore-duplicates` (so a re-park never restarts the deadline or un-lives a row). The existing prod row a25e00ff (alignable.com, parked 11/13 as sms) therefore kept `verification_type=sms` when t_2884b89d re-parked it as phone-call. Right table and row; the park skips existing rows.

## Change (job/transitions.py only)
After the ignore-duplicates upsert, for sms/phone-call parks send one PATCH scoped to client_id + directory + `state=requires_verification` + `verification_type=neq.<new>`, body `{verification_type, updated_at}`. Postcard/id-check untouched (deadline/steps). Live rows never touched.

## Tests (offline)
tests/transitions_test.py T14: PATCH scope/body for sms and phone-call, none for postcard, dry run no calls; existing T10/T13 and park_any_tenant counts narrowed to POST.

## ERROR_TEXT (item 5): SKIPPED
Per Nate (t_4ee21e60 review): the ERROR_TEXT/LANDED_TEXT change goes into the t_4ee21e60 rework PR so one PR edits step_sent. Not touched here.
