# Plan 2026-10-26: batch 9 fixes (kanban t_d7a907d5)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-25-batch8-fixes.md. Applied from it: stdlib only, tests mock every network edge and browser, NO live queue write (batch 10 owns the queue file), no Directory submit/edit, new tests go in CI.

1. **recheck exact name.** `exact_name()` = lower + whitespace + `&`/`&amp;`/`and` only. `compare()` adds a `name` mismatch when the block's first line is not exactly the canonical name; `read_block()` prefers an exact line over a near miss, still reads a near miss so the field is named. Street: type must match (Dr = Drive only); "street+city on one line" must continue with the city. Test: Yellowpages "Senior Care Consltng Solutions" -> `mismatch: name`.
2. **Generic runner.** `job/formspec.py` loads `job/playbooks/<site>.json` (steps: open, clear_ads, fill, select, upload_logo, click, wait_mail, stop_before_submit) and builds a `Site` of ordinary Steps with NAP keys (`{name}`, `{street}`...). `build_runner.py` falls back to a JSON spec when no Python module is registered. Proof: citylocalpro.json, `--dry-run`.
3. **`pagekit.select(page, label_or_selector, text)`** detects native / select2 / Choices.js.
4. **`pagekit.clear_overlays`** (fixed + high z-index layers covering the target) and **`find_in_frames`** (same-origin iframe submit button). `clear_ads` calls the overlay pass.
5. **Chrome keepalive.** `build_chrome.ensure_up()` checks 9333 and starts the same persistent profile detached; `build_runner.connect()` calls it before a step; a lease file (`build-chrome.lease`) with a card id makes the `--seconds` timer refuse to close while a lease is fresh.
6. **Vault helpers** (citation-submitter profile scripts, outside the repo): `tmp-dir.js` + use in write/mkpayload/fill/exercise; `not-found` on zero matches. Node tests.
7. **Fit.** `homepage_flag()` -> verdict `flag` (not rejected by `--write`); nashvegas.com and maplenmain.com -> `niche-other` in the seed generator, seed JSON and migration SQL (additive data; prod ce_directories PATCH is NOT done here, listed in the handoff).
8. **recheck unreadable.** ENTRY_RE adds payment/checkout/submission; no permalink -> Directory name+city search -> same-host listing link.
9. **Read check** loc8nearme.com cost fields (GET only).
10. **Trigger.** build_runner does not call `buildqueue.submit_row`; report in handoff, no t_426da7c5 change.
