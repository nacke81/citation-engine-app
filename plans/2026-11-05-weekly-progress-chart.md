# Plan: weekly progress line chart (t_43e88fb7)

Latest lesson read: docs/lessons/2026-11-04-every-park-path-names-its-own-reason.md ("a dry run that does not echo a field cannot prove the field"; find every path by grep, not by list).
Applied here: the backfill dry run prints the source of every cell, and the snapshot writer is the one path the weekly job uses (grep'd: only `job/run.py main()` writes ce_runs).

## Findings that shape the design
- Tiles live in JS (`site/builder.js` builderStats/checkedStat, `site/logic.js` stats). The weekly job is Python. So the job does not re-implement the counts: it pipes rows into `job/metrics_cli.mjs`, which imports the same `site/metrics.js` -> `builderStats`/`stats`/`checkedCount`. One source of truth, not a mirror.
- Home tiles are in `overviewHtml` (both businesses on the home page). Chart goes inside each business card, after the `<h2>` and before the stats. When a footprint_snapshot summary exists the first six tiles are swapped for Live/In progress/...; the chart still plots the six check metrics. Noted for review.
- ce_runs (prod, read-only look): 5 ok runs. 10/16 16:30 and 10/16 19:44 are the same day (rerun); 10/18, 10/25, 11/01 are the Sunday weekly runs.
- Queue history (SCC only, local queue file) starts 2026-10-21 and is date-only. NM has no queue rows. claim_status / agent_access / proof fields are current-only.

## Rules
1. Points = week 0 (first ok run) plus every later ok run that is not a same-calendar-day rerun of the previous point (backfill classifier). Going forward only `run.py --weekly` writes a snapshot (weekly.cmd passes it); manual runs and rechecks write none.
2. Six check metrics: from ce_checks of that run (same `stats()`/`checkedCount`).
3. Six queue metrics, past weeks: enumerate every state each directory could have been in at the run date (history events before the day = certain, same-day events = either side, before first event = absent or queued, claim_status and agent_access unknown, proof by proof_at). Run the REAL `builderRows` per possible world. A metric is filled only if its count is identical across all worlds; otherwise null (gap). Never interpolated.
4. Table `ce_weekly_metrics(owner, biz, run_id, week_index, captured_on, metrics jsonb, sources jsonb)`, unique (owner, biz, run_id), RLS select-own like ce_runs. Writer is insert-ignore-duplicates, so a rerun is a no-op.
5. Chart: hand-rolled SVG in `site/chart.js` (pure html builder + `wireChart`). Legend = one checkbox per metric, all on by default, saved in localStorage `ce-chart:<biz>`. Hover = SVG `<title>` per point. Null breaks the line. Tiles untouched.

## Files
- site/metrics.js (shared pure), site/chart.js, site/render.js (insert chart), site/app.js (load table, wire), site/index.html (css)
- job/metrics_cli.mjs, job/weekly_metrics.py (classifier, snapshot writer, backfill dry/write), job/run.py (`--weekly` hook at end), job/weekly.cmd
- db/012_weekly_metrics.sql + schema.sql
- tests: tests/metrics.test.mjs, tests/chart.test.mjs, tests/weekly_metrics_test.py; CI steps.

## Out of scope / not done by this card
Applying migration 012 or the backfill to prod, merging: Nate/Mike gate. No directory traffic.
