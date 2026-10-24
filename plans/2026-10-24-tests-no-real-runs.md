# Plan 2026-10-24: tests must not create dirs in the real runs folder (kanban t_8db05c29)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-24-resolver.md. Applied from it: stdlib only, no schema change, no change to job/ code, base origin/main bd09dfe.

## Problem
job/run.py runs os.makedirs(RUN_DIR) at import. Tests that import run without CE_RUNS leave an empty runs/<stamp> dir under %LOCALAPPDATA%/citation-engine/runs.

## Design
1. Each test that imports run (create_test, dry_check_run, golden, listing_test, permalink_test, portal_test, proof_test, resolver_test) sets os.environ["CE_RUNS"] to a fresh tempfile.mkdtemp() before the import. weekly_claim_test already does. tests/resolver_dry_run.py sets CE_RUNS to its --out dir.
2. New tests/runs_dir_check.py (CI): source scan of every tests/*.py. If a file imports run, an assignment to CE_RUNS must appear earlier in the file. Planted control: a synthetic bad source must be flagged. Also snapshots the real runs folder before and after, and fails if it grew. Added to ci.yml.
3. rmdir the six empty dirs 20261024-1802, 1803, 1804, 1805, 1814, 1815. No rm -rf.

## Verify
ls of the real runs folder before and after the full local suite: no new entries. CI green.
