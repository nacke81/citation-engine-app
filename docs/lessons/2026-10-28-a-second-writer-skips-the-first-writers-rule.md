# 2026-10-28 — A rule kept by one caller is not a rule

- Proof was written by the two callers that moved a row to live (weekly `proof_step`, `recheck --write`), each doing its own upsert before calling the transition. `record_transition` itself accepted `live` with no Proof, so the CLI, a human-verified move, or any later caller could set live with all five Proof columns null. The weekly run printed PROOF OK because it only audited its own movers.
- Put the invariant in the one writer: `record_transition(..., proof=)` refuses a move into live without complete Proof, before any write, and the Proof rides in the same `ce_directory_status` upsert as `queue_state=live`. A pre-write by the caller is not a substitute.
- Add a guard that reads the whole queue (`live_rows_missing_proof`, `transitions.py --audit`) so a green weekly run cannot hide rows it never touched. Test it with a null in each field, not only a missing dict.
- A source-scan test that lists every call site naming the live writer catches the next new path; it is cheap, and it fails loudly.
- Backfill for already-live rows goes through the same validator (`record_proof`), is dry-run by default, and refuses rows that are not live or already complete. The card that ships the command must not run it on production.
