# 2026-10-28 — No live row without Proof (t_d660babc)

Latest lesson read: docs/lessons/2026-10-28-batch22-fixture-not-account-proof.md (fixtures prove guards, not live behavior; run every existing suite).

## Finding
Every `state=live` write funnels through `transitions.record_transition` (queue file + `D.sync_transition`). Callers: `proof.proof_step` (weekly), `recheck._proof_then_live` (recheck --write), `recheck` refresh-url (live->live), the `transitions.py` CLI (`--to live`), `buildqueue.submit_row` (only submitted/created-unlisted; refuses live), `lookup --set-url` (same-state, refuses live), `mail_scan` (read-only). The Proof columns were written by a *separate* upsert in the two callers, so any other caller (CLI, a human-verified move, needs-human -> live) could set live with no Proof. Nothing in the writer enforced it.

## Change
1. `transitions.record_transition(..., proof=None)`: a move INTO live (not the live->live `refresh_url`) requires a complete `proof` dict (proof_url http(s), proof_nap non-empty, proof_at, proof_nap_match is True, build_action in new|claim|fix). Missing/incomplete -> `TransitionRefused` before any write (queue untouched). `proof` on a non-live target is refused. The proof is stored on the queue row (`row.proof`) and written in the SAME `ce_directory_status` upsert as `queue_state` (`D.sync_transition(proof=)`).
2. `transitions.record_proof(row_id, proof, ...)`: Proof for a row already live (backfill / `--proof-live`), same validation, one writer.
3. `transitions.live_rows_missing_proof(queue)` + `transitions.py --audit` (read-only): lists live rows with an incomplete `proof` on the queue row.
4. CLI `--to live` has no proof arguments: it fails closed.
5. `proof.proof_step` and `recheck._proof_then_live` pass `proof=` instead of a pre-upsert. `recheck._proof_only` -> `record_proof`.
6. New `recheck --proof-backfill --row ID`: dry-run by default; `--write` reads the signed-out page via the existing read path and writes Proof through `record_proof`. Requires `--row`; only live rows; state unchanged. No Directory action beyond the existing signed-out GET. NOT run on production by this card.

## Tests (tests/proof_gap_test.py, in CI)
One per live-writing path: proof_step, recheck --write, CLI, needs-human->live direct, pending-verify->live direct, record_proof, backfill; negative: each missing field refuses and leaves the queue file byte-identical; guard: a live row with a null proof field fails the audit; no portal-seed/Directory call on the non-prod path (poisoned urlopen). Existing suites that moved a row to live get a proof fixture.
