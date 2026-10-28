# 2026-10-28 — channel_label on every listing activity (t_ef2b05e9)

Latest lesson read: docs/lessons/2026-10-28-batch22-fixture-not-account-proof.md (fixtures prove guards, not live behavior; run every existing suite).

## Finding
`job/transitions.py build_activity_record` is the only builder of `deliverables` rows. It sets no service assignment and no `channel_label`, so the portal shows the row under "Additional work".

## Change
1. Add `ACTIVITY_CHANNEL_LABEL = "SEO & Local SEO"` and put `"channel_label"` in the record (one field; shared contract with t_9bc7d948).
2. New `tests/channel_label_test.py` (no network): live, submitted, pending-verify, rejected each carry the label; the label is in the upsert body of `record_transition`; no other key changes.
3. Add the suite to CI.

## Out of scope
No prod write, no backfill (paired card), no runtime-clone edit.
