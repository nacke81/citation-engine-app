# 2026-11-04: a label read out of free text also matches the text that denies it

- The audit mapped gate text to a reason with regexes. Two rows came out wrong in ways a regex cannot see: a note saying Cloudflare was gone read as a Cloudflare wall, and a note saying no CAPTCHA was solved read as CAPTCHA.
- Fix: the page never reads gate text for the label. The worker that parks a row stores a `reason_code`; everything else comes from a column that holds one fact (catalog `cost`, `dead`, the check row's `result` and `note`). The audit mapping ran once, as a backfill, and was hand-checked against all 61 rows.
- The cause of a wall has to be written by the code that saw the wall, from the status token it got back (`blocked: http-403`), not recovered later from prose. 10 of 27 Couldn't check rows said only "blocked" because the job threw the status away.
- Changing a note's shape (`blocked` -> `blocked: <kind>`) breaks every reader that tests `== "blocked"`. Grep every reader first. Three needed a prefix match; a test now runs the agent-blocked update on both shapes.
- Adding a column is not enough when the page reads a view: the view had to be recreated with the column appended last. Test the migration text for that.
- A fixture cut from prod must be scrubbed of client names, cities and phones. The leak check caught it; the label logic never reads gate text, so the fixture does not need it.
