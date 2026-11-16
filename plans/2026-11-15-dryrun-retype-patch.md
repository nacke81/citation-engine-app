# Plan 2026-11-15: dry run shows the retype PATCH; retype clears postcard/id-check-only fields (t_fd2f38d0)

Cites latest lesson: docs/lessons/2026-11-15-verify-speed-and-landed-send.md (and PR #123's retype, t_5148d0b9).

1. Schema check (platform-repo migrations, read-only): deadline timestamptz, steps text[], directory_url text are all nullable; steps/directory_url CHECKs allow null. All three go in the PATCH body as null.
2. One shared builder `retype_request(client_id, directory, verify_type, now)` -> (path, body), used by the write and the dry run.
3. Dry run: `verification_request` becomes a list [POST upsert, PATCH retype] for sms/phone-call parks, [POST] for postcard/id-check. The live transition stays a single dict.
4. Tests (transitions_test.py): sms and phone-call dry run lists both with the exact path/body the write sends; postcard has no PATCH; nulls present. Update T11 and park_any_tenant test 4 for the list shape.
5. Mutation: drop the PATCH from the dry run, confirm a test fails.
