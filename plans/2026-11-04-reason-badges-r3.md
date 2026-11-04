# 2026-11-04 Reason badges, round 3 (t_93ae9b6b, PR #74)

Cites lesson `docs/lessons/2026-11-04-a-label-from-free-text-matches-its-own-negation.md`: one stored source of truth per label; a second writer that disagrees corrupts it. Here the weekly re-assert was a second, wrong writer of reason_code.

Nate round 2 change (one item): the weekly path must not clear reason_code. In prod 4 coded rows are rejected/submitted (yellowbook, facebook, localstack, bbb.org); a weekly null would wipe them.
1. `queue_rows_to_status` never sends the reason_code key, any state.
2. Clearing stays in `sync_transition` only (unchanged).
3. Tests: R12 flipped (no weekly row has the key); R13 flipped (needs-human, rejected, submitted keep codes through sync_run); new R14 with the real 4-row shape (rejected x3, submitted x1, each with stored code, all unchanged). R11 kept.
No prod writes. Do not merge. Dispatch CI on new head.
