# Plan (round 2): put the deliverables invariant in Portal.call (t_25000cbd)

Cites lesson `docs/lessons/2026-11-18-one-writer-or-the-guard-is-a-wish.md` (latest): a grep guard that matches the table-name string is a wish; a module can reach the table through the exported constant. Review round 1 on PR #139 proved it (job/backfill_y.py with P.DELIVERABLES_PATH passed 13/13).

Change: `portal.guard_deliverables` runs first in `Portal.call`. Any non-GET to table `deliverables` must be POST to exactly DELIVERABLES_PATH with a list of dict rows; each row is rebuilt through `deliverable_row` (None/empty approved_at replaced by a timestamp, an existing stamp kept, source forced); client allow-list checked; PATCH/DELETE/other on_conflict/case or slash variants raise PortalWriteError before the opener. `portal.deliverables_request` serves the dry run so transitions never names DELIVERABLES_PATH. Guard test also flags any DELIVERABLES_PATH Name/Attribute outside job/portal.py. Nits: transitions header indent; same `now` passed to write_deliverables.

Tests: deliverables_helper_test (planted M1 + bare import must FAIL the guard; opener-based transport checks; 3 mutations of Portal.call caught), transitions, channel_label, portal, no_prod_portal_sink. Not built: existing-listing "confirmed live" rows (child t_d9ed56f5).
