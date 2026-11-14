# Plan: show every Directory's playbooks in the Directories tab, backfill them, write them back (t_2cb780c2)

Cites lesson `docs/lessons/2026-11-13-one-source-for-the-steps.md` (one record, placeholders only, validate at write and render). Base: origin/main 393d5d9 (PR #109). PR #110 (contact_name, signin_url) is still open; this branch does not touch its files except `job/playbook.py`, and only by adding one optional `stale` parameter (expect a trivial merge).

## What changes
1. **App** (`site/directories.js`, `site/app.js`, `site/index.html` css if needed). `load()` adds a read of `ce_directory_playbooks` (select `*`, same client and RLS as `ce_directories`, `.catch(() => [])` so the tab still works before the table or with no rows). `directoriesHtml(dirs, rows, f, openDomain, playbooks)` passes the open Directory's rows to `detailHtml(d, pbs)`. New `playbooksHtml(pbs)`: one block per task in fixed order check / create / claim / fix / verify. Block = title, numbered steps (text escaped, url through `safeUrl` as a link, selector in `<code>`), "Last proven <date>" or "Never proven", "Source: <source>", "v<version>", a "Stale" chip when `stale`, and "No playbook yet" when the task has no row. All text through `esc`.
2. **Migration 018** `stale boolean not null default false` on `ce_directory_playbooks`. Applied through `db/apply.py <ref> db/018_playbook_stale.sql` (apply.py gets an optional file argument; default stays schema.sql). Not applied by this PR.
3. **playbook.py**: `set_playbook(..., stale=False)`; the key goes into the row only when stale is true or the stored row already has the column, so a prod table without 018 keeps working. A set with `last_proven_at` clears stale. File key `stale`.
4. **Backfill** `job/playbook_backfill.py`: reads vault `playbooks/build/*.md` and the `ce_directories` rows, builds rows per (domain, task), runs every row through `playbook.validate_steps`, drops (and counts) any sentence that fails or that holds a tenant value. Tenant values come from the identity file at run time (never hard-coded; the repo leak check bans them). Default is dry run with a JSON report and counts per task; `--write` goes through `set_playbook`. `last_proven_at` is always null (a backfill is not a run that reached its goal). A note whose title or outcome line says rejected / no-fit / blocked / dead / 404 is written with `stale` true.
5. **Write-back rule**: Verify Now prompt (`verify_send.build_prompt`) ends with a write-back instruction (run `playbook.py set` for the verify task when the steps changed or were proven; `last_proven_at` only after `result --outcome accepted`). The PR #107 trace (`verify-traces/promote/*.json`) feeds verify: new `playbook.py from-trace <file>` turns a promote file into a verify step list (text from action, url, selector; query-less urls already) and sets it with `last_proven_at` = trace `saved_at` because promote_trace only fires after a clean send. The citation-submit skill lives in the `citation-submitter` profile, which this seat does not edit; the exact text is committed as `docs/playbook-write-back.md` for Nate to carry into the skill.

### Decisions made during the build
- The Verify Now agent has no service key and is told it never runs the portal; so the prompt (step 8) asks for a `PLAYBOOK-NOTE:` line and `playbook.py set` is the rule for runs that hold the key (docs/playbook-write-back.md). Auto-running `from-trace` after an accepted result is left to Nate (it adds a DB write to the verify path).
- Backfill drops a sentence rather than scrubbing it; a stale directory gets an "Old note, not a verified step" row so the page does not say "No playbook yet" about a site that was tried. Lesson written: `docs/lessons/2026-11-13-a-backfill-is-not-a-proven-run.md`.

## Tests (house pattern: real markup, no DOM)
- `tests/directories.test.mjs`: task with steps (numbered, link, code, date, source), missing task ("No playbook yet" per task, all five blocks present), escaped step text (`<script>` in text/selector, `javascript:` url shows no link), stale chip.
- `tests/playbook_backfill_test.py`: classification, tenant value dropped, email/phone only scrubbed when it matches identity, every row validates, stale detection (thumbtack), counts, never writes on dry run, mutation (denylist off -> a tenant value gets through).
- `tests/playbook_test.py` additions: stale param, from-trace.
- CI: add the new python test to the workflow.

## Evidence plan
PR URL + head, command output, backfill dry-run counts per task, screenshots of thumbtack.com expanded at 390px and 1440px from a local static page with the real module and the prod thumbtack verify row shape (the prod Pages deploy only exists after merge; stated in the handoff).

## Out of scope
Fence, tenant lock, portal write, applying 018 or running `--write` against prod (post-merge step, needs Nate's go).
