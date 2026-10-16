# Plan 2026-10-16: hide the Chrome window-count line (kanban t_3272cc75)

Latest lesson read: none exists (repo has no docs/lessons). Prior plan: plans/2026-10-16-gate4-changes.md.

## Decision
- Remove the run-health line from the overview render (site/render.js) and delete windowLine from site/logic.js. Mike does not need it on the page.
- Data stays: chrome_* and owned_alive_after columns are untouched. No job, DB or schedule change.

## Tests
- Replace the windowLine unit test with: a run carrying chrome_* fields renders an overview with no "Chrome windows" text, and no served file under site/ contains "Chrome windows".
