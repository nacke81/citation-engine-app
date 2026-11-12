# Plan: Verify Now slice 1, agent side (t_0d601426)

Cites lesson `docs/lessons/2026-11-12-one-decision-function-for-both-paths.md`: put each decision in one function that returns a verdict, and test every verdict. Here: `verify_bridge.fence()` is the one decision (`ok | bad_client | channel | no_row | mismatch | no_playbook`) and both the bridge and the send run call it, so they cannot drift.

Scope (new files only, plus one CI line):
1. `job/verify_bridge.py`: `VerifyRpc` (the 4 contract RPCs, exact names and arg names, allowlisted status and fail codes), `fence`, `sweep` (10 min, finish could_not_start/timeout, one Kanban card per request via idempotency key `verify-now:<id>`), `run_pass` (sweep, then claim up to 3, fence, start the send run as a direct subprocess). No scheduler.
2. `job/verify_send.py`: the send run for Cylex SMS. Re-checks the claim and fence, vault lookup (fail closed), sitegate reserve (1 read per request), per-tenant owned Chrome (off-screen), sign in, email access code first (relay file or IMAP), phone modal, send, `mark_code_sent` with a masked number, 10 s code poll for 30 min, enter code, read result, set row live, `finish_code_request('verified')`. Browser and mail are injected, so tests use a fake page.
3. Direct-run command for the submitter seat is documented in the module docstring and verified with `hermes -p citation-submitter chat --help`.
4. Tests `tests/verify_bridge_test.py`: strict fake of the 4 RPCs, happy path, 30 min timeout, sweeper twice, no-playbook zero loads, client mismatch refused before any network call, leak test over every failure path.
5. CI: add the test step.

Decision: "set live" PATCHes `citation_verification` (state live, verified_at), the same verification-queue step `transitions.record_transition` performs on a move to live. The queue row's own move to live still needs public-page Proof and is NOT bypassed here.
Open contract item: the request table name for the sweeper's list read is not in the contract; `REQUEST_TABLE` is a constant, to confirm against the portal migration.
No real send, no CapSolver, no prod write.
