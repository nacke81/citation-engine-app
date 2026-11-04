# 2026-11-04 Reason badges on "Needs a person" and "Couldn't check" (t_93ae9b6b)

Cites lesson `docs/lessons/2026-11-03-two-comparators-looser-wins.md`: two rules on one page means the looser one wins. So there is ONE label function (`site/reasons.js`), used by both sections, and free-text regex is not a second writer of the label.

Stacked on `t_3a7fdcfe-collapsible-sections` (PR #73, head 6a9418f). PR base = that branch until #73 merges. Badge goes inside the new `section()` row markup.

## Rulings applied (Nate, 11/04)
1. `Blocked: Cloudflare` split from `Blocked: bot wall`.
2. Stored `reason_code` (nullable text) on `ce_directory_status`. Free-text regex is NOT used at read time. The audit mapping is a one-time backfill. cylex.us -> Signup form fails, usaypage.com -> Form can't take our NAP. NAP rule ahead of CAPTCHA in the backfill order.
3. `job/walls.py` records the wall kind / HTTP status in `ce_checks.note` as `blocked: <kind>`. Until a row has that, `blocked` alone shows "Blocked (cause unknown)".
4. data-axle.com stays in Needs a person with its label.
5. Migration 011 is written and tested locally only. NOT applied to prod. Nate rules the apply in review; it must be applied before merge (10/20 lesson).

## Design
- `db/011_reason_code.sql`: `alter table ... add column if not exists reason_code text` (no constraint, additive, idempotent). Also added to `db/schema.sql` if it lists columns.
- `db/011_reason_code_backfill.sql` (generated, NOT applied): one `update ... where biz=? and directory=? and reason_code is null` per row for the rows whose label needs gate text. Rows whose label derives from a stored field (check note / result) are left null on purpose. Source map in `db/reason_backfill.json`, generator `db/gen_reason_backfill.py`, built from the audit table with the two fixes.
- `site/reasons.js` (pure): `REASONS` code -> {label, tone}; `reasonFor({row, status, dir, check})`:
  1. `status.reason_code` if it is a known code.
  2. stored fields only: `ce_directories.dead`/`cost='paid'`/`build_route='agency-account'`, `ce_checks.result='unsearchable'`, `ce_checks.note` (`blocked: cloudflare|captcha|http-NNN`, `blocked`, `no usable result`).
  3. else `Other: see gate`.
  No `queue_note` regex.
- `site/builder.js`: builderRows adds `reason` {code,label,tone}. `site/logic.js` cantCheckCards takes optional status/dirs and adds `reason` label; `reasonOf` accepts `blocked: x`.
- `site/render.js`: colored badge next to the directory name in flightRow (Needs a person) and the Couldn't check row; gate text stays below. Filter control (a `<select>` or chip row with counts) at top of Needs a person. Filter state is a pure input (`open`-style arg), so render stays pure; `app.js` holds the value and re-renders.
- `job/walls.py`: `wall_kind(status, text)` + `job/run.py cant_reason` returns `blocked: <kind>`. Exact-match consumers of `note == "blocked"` (directories.py, portal.py, listing.py, logic.js) change to prefix match. No change to the build loop or submit logic.
- Writer: `job/transitions.py` / `directories.sync_transition` on needs-human writes `reason_code` when the caller passes one (`--reason-code`, validated against the code list). Optional, additive.

## Tests (real row shapes)
- `tests/reasons.test.mjs`: fixture of the 61 rows (stored fields + backfilled code from the JSON) -> every row gets a label, Other < 5% (target 0), label=count readback equals the audit counts after the rulings; cylex and usaypage not CAPTCHA/Cloudflare; data-axle in Needs a person with label; badge present in both sections and gate text still below; filter shows only Paid rows; unknown reason_code falls to derivation, never throws.
- `tests/walls_test.py`: wall_kind cases; cant_reason emits `blocked: http-403`; exact-match consumers still treat it as blocked.
- Backfill: generator output is stable, covers 61 keys, only touches `reason_code`, contains no insert/delete.
- Existing `npm test` and python tests stay green.

## Evidence
PR (base = #73 branch), CI, 1440px screenshots of SCC Needs a person and Couldn't check (local render over the read-only prod rows), label=count readback of 61 rows.

## Not doing
No prod apply, no prod row edit, no section moves, no build-loop/submit change.
