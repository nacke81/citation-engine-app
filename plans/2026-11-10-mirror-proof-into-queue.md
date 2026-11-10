# Plan: mirror ce_directory_status Proof into live queue rows (t_78dc54b5)

Latest lesson read: docs/lessons/2026-11-09-a-guard-must-read-the-row-not-the-constant.md (pin the data the engine reads; watch the test fail on a mutation).
Applied here: tests run the real writers (record_transition, buildrows.apply_file, weekly_merge) on a queue with a live row that has no `proof` key and a stub DB that holds complete Proof, and a mutation check removes the hook and watches them fail.

## Why
12 SCC live rows (built 10/25-10/27) have complete Proof in prod ce_directory_status but no `proof` key in the queue file. On 2026-11-10 two readers ran proof_problems(row['proof']) on the file and counted SCC 10 of 38 instead of 22 (t_21e17f0c, t_3eab7673). The engine guard (live_rows_missing_proof with db_proof) was right; the file was wrong.

## Scope (job/ only; no DB write, no row state change, no submit)
- transitions.mirror_proof(q, db_proof): for every live row whose own `proof` is missing or incomplete (proof_problems != []) and whose DB copy is complete, set row["proof"] = the 5 PROOF_FIELDS. A complete queue proof is never touched. db_proof None (sink off) => nothing. Returns filled row ids.
- transitions.mirror_proof_quiet(q, db): fetches db_proof_by_directory only when a live row needs it; any DB error is printed and swallowed (queue write is never blocked).
- No single shared queue writer exists (transitions._write_atomic, buildrows.apply_file, create_discovery.weekly_merge each write), so hook all three:
  - record_transition and record_proof (covers recheck --write, which writes through them) before _write_atomic.
  - buildrows.apply_file(db_proof=...) mirrors before the no-change test; main() and run.buildrows_step pass it.
  - create_discovery.weekly_merge(db_proof=...); run.create_queue_step passes it.
- One-shot: `python job/transitions.py --mirror-proof [--write] [--queue PATH]`. Dry run lists rows; --write backs up (.bak-<day>-mirror-proof), writes atomically, prints md5 before/after. Sink off => prints SKIPPED, exit 0, no write.
- tests/mirror_proof_test.py + CI step.

## Gates
Merge by the standing rule, then run the one-shot --write on the runtime queue (backup first). No portal call, no Directory request.
