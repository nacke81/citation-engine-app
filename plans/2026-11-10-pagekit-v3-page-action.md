# Plan: reCAPTCHA v3 pageAction in pagekit + logged CLI wrapper (t_bc10b2d3)

Latest lesson read: docs/lessons/2026-11-10-a-file-readback-must-mirror-the-source-of-truth.md (fix every writer, not each reader; run a mutation check).
Applied here: one logging path (pagekit.solve_captcha) is reused by both the page flow and the new CLI wrapper, and a mutation check proves the tests fail when pageAction or the log line is removed.

## Why
findcarez.com (reCAPTCHA v3, action `register`) needed hand steps in t_5d6deb42: pagekit.solve_and_inject had no pageAction, the injected token was not what `grecaptcha.execute` returned, and a direct CLI solve wrote no log line.

## Scope (job/ + tests only; no network, no real CapSolver, no .env read)
- captcha_route.argv: `extra` is passed as `--extra <json>` for every widget type (was image only).
- pagekit.solve_and_inject(..., page_action=None): v3 only. Explicit page_action wins; else auto-detect `grecaptcha.execute(key, {action: 'x'})` from page HTML (nice-to-have). Passes extra={"pageAction": a}. Result gains `page_action`. v2/turnstile never get pageAction.
- pagekit.inject_token: for v3 also overrides `grecaptcha.execute` (and enterprise.execute) to resolve the token; token goes into every `[name=g-recaptcha-response]` (already does).
- job/capsolver_solve.py: wrapper for hand/CLI use (`--row --kind --url --sitekey [--page-action] [--extra]`); calls pagekit.solve_captcha so each CLI call appends one line (row, kind, ok, cost, note) to the solve log; failure => ok=false line, exit 2. Prints one JSON line like the CLI.
- tests/pagekit_v3_test.py + CI step.

## Gates
PR to main, CI green, independent review. No live submit, no spend.
