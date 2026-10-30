# 2026-10-30 Your-turn gate (t_e2db63f0)

Cites latest lesson: docs/lessons/2026-10-28-batch22-fixture-not-account-proof.md (a fixture is not account proof; so the gate demands an observation made on the live verify step, and the test uses real row shapes from 10/30).

## Why
Mike worked all 9 SCC citation_verification rows on 2026-10-30. Four were wrong: ezlocal (email verify, DB said sms, agent-doable), ibegin (vendor sends no verify), showmelocal ($6.99, paid), com-yellowpages (redirects to bestyell.com). Each was parked on Lea Ann without an agent looking at the live verify step.

## Change (code, not prose)
- New `job/your_turn_gate.py`: pure `check_your_turn(directory, verify_type, observation, dir_row=None, today=None)` -> list of refusals.
  Observation must carry: `observed_type`, `screenshot` (existing non-empty file), `price_seen` (a number, or "none"/"free"), `observed_at` (date, within 7 days of today = "this cycle"), `url` (https, no userinfo).
  Refuse: missing/stale observation; observed type != parked type; observed type email/email-link (agent job via listings@); price > 0 or "paid" word; Directory DB row dead, cost paid, or url redirect-off-domain (observation `final_url` host != directory host).
- `transitions.record_transition(..., observation=None, dir_row_lookup=None)`: any `verify_type` (the Your turn write) runs the gate BEFORE any write; refusal raises TransitionRefused with nothing written. Directory DB row looked up via `directories` sink (injectable; dead/cost flags).
- CLI flags `--observed-type --screenshot --price-seen --observed-at --observed-url --final-url`.
- Tests `tests/your_turn_gate_test.py`: the four 10/30 failure shapes refused, a clean phone-call observation accepted, every existing needs-human/verify test given a valid observation. No network.

## Not in scope
No portal schema change (rows stay in citation_verification), no new listings, no paid claims.
