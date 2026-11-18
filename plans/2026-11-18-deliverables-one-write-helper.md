# Plan: every `deliverables` write goes through one helper that always sets approved_at (t_25000cbd)

Cites lesson `docs/lessons/2026-11-18-a-zero-needs-a-reason-it-could-see.md` (latest at start): a "0 held" is only true if the guard can see every path. So the guard scans the whole tree, not a list we maintain.

## Finding
Grep of job/, db/, tests-excluded tree: the only `deliverables` writer is `transitions.record_transition` (via `build_activity_record` + an inline `act.call("POST", "deliverables?on_conflict=...")`). It still carries a hold path (`CE_ACTIVITIES_HOLD=1` / `activities_hold_flag`) that writes `approved_at` null. No script or backfill writes the table today; the next one would copy the inline path and could skip approved_at.

## Change
- `job/portal.py`: `DELIVERABLES_PATH`, `deliverable_row(fields, now)` (forces source=citation_engine, approved_at=now, ISO UTC; overrides any caller value incl. None) and `write_deliverables(portal, rows, now)` (the ONE POST; every row passes deliverable_row; check_client first).
- `job/transitions.py`: `build_activity_record` uses `P.deliverable_row`; the write and dry-run use `P.write_deliverables` / `P.DELIVERABLES_PATH`. Hold path removed (Nate ruling: no row may land held). `activities_hold_flag` kwarg stays accepted and ignored so callers don't break.
- `tests/deliverables_helper_test.py` (+ CI step): helper behaviour; AST/regex guard over every job/**, db/**, site/**, root script file that a `deliverables` table path/SQL appears only in portal.py; mutation 1 (portal source with approved_at dropped) fails the behaviour checks; mutation 2 (a temp job module writing deliverables directly) fails the guard.
- Update T6h/CL tests: hold is now ignored, approved_at always non-null.

## Proof
New test, transitions_test, channel_label_test, portal_test, no_prod_portal_sink_test, py_compile. Then PR, merge under standing rule, pull runtime clone, prod read of `deliverables?source=eq.citation_engine&approved_at=is.null` = 0 (read only).

## Proposal (not built)
Existing-listing (`record_existing`) rows write no Activity; proposal goes in the handoff.
