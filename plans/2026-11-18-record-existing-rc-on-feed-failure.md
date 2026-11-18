# Plan: `--record-existing` exits 1 when the client-row post failed (t_9f3a9323 step 3)

Cites lesson `docs/lessons/2026-11-18-one-writer-or-the-guard-is-a-wish.md` (latest at start): no new writer; this only changes what main() reports about the existing one.

## Change (job/transitions.py main(), `--record-existing` branch only)
After printing the JSON, return 1 when `res["errors"]` is non-empty (activities_written false), and print to stderr the retry command
`python job/transitions.py --existing-activity --client SCC --row <res["row"]["id"]>`. The queue and status writes stay (no undo). Dry run, a clean write, and CE_ACTIVITIES_WRITE=0 (no errors) still return 0.

## Tests (tests/existing_activity_test.py)
R1 failing portal (P.write_deliverables raises) through `T.main(["--record-existing", ...])`: rc 1, queue row still written, retry command on stderr. R2 clean fake: rc 0. Mutation M5: restore `return 0` -> R1 FAILS.
