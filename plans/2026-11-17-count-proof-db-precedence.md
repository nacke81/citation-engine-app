# Plan: pin DB-proof precedence in count_proof (t_be2150cd)

Cites lesson `docs/lessons/2026-11-17-count-it-but-do-not-claim-it.md` (latest at start): the count must follow proof, so a test must show proof from each source is honoured.

## Gap
Mutation of `job/portal.py count_proof` (`if not T.proof_problems(v): proof[k] = v` -> `pass`) passes the whole suite. A live queue row with no `proof` key (pre-guard row) whose proof is only in ce_directory_status would be re-stated to couldnt_check on the client page.

## Change (tests only, plus one guard)
- `tests/snapshot_count_basis_test.py`: through `write_run(..., proof_by_dir={dom: complete proof})` with the queue live row lacking `proof`: written row stays `live`, count 24. Also: incomplete DB proof does not override a complete queue proof; incomplete DB proof with no queue proof is re-stated. Direct `count_proof` asserts. `proof_by_dir` always explicit, never prod.
- Re-run the mutation; it must fail.
- `tests/snapshot_test.py`: set CE_DIRECTORIES_WRITE=0 at the top (see finding).

## Prod finding (read-only)
Prod ce_directory_status SCC has `a.example` (fix-a, pending-verify, 2026-10-26) and `b.example` (fix-b, submitted). Writer: `tests/snapshot_test.py` S3/S4 (`record_transition` without `directories=`, sink not off -> `D.DirDB()` prod when run locally with prod env; CI has none). Removal is a prod delete: needs-mike.
