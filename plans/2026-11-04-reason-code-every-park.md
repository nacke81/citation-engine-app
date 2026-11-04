# 2026-11-04 reason_code on every needs-human park (t_8d61ef01)

Cites lesson `docs/lessons/2026-11-04-a-label-from-free-text-matches-its-own-negation.md`: the code that parks a row stores the reason; nobody recovers it later from prose.

Scope guard (Nate, card comment): `directories.queue_rows_to_status` (weekly) is NOT changed. It never sends reason_code; clearing stays in `sync_transition`. Existing weekly-path tests stay green.

Changes
1. `transitions.record_transition`: validate reason_code up front (in REASON_CODES, only on a move to needs-human) -> TransitionRefused before any write. Store it on the history entry. Echo `reason_code` in the output, and in dry-run as `directories_request`.
2. `buildrows.make_row`: needs-human-paid -> `paid`, needs-human-route -> `signup_form`, on the history entry.
3. `walls.record_try` try 3: `bot_wall`, or `cloudflare` when a Ray ID was given; on the history entry.
4. `recheck` no-public-permalink park: pass `reason_code="no_search"` (goes through record_transition -> sync_transition).
5. `captcha_route.plan` park notes and `build_runner` record:none hint name `--reason-code`.
6. Items 2-3 only land on the queue history entry (queue file). Carrying it to ce_directory_status needs sync_transition or a backfill: a separate Nate/Mike call. No prod writes.

Tests: tests/reason_code_paths_test.py (plain-python check() style), real row shapes.
