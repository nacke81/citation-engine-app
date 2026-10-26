# Plan 2026-10-25: batch 7 fixes (kanban t_d13bd638)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-25-recheck-and-fixes.md. Applied: stdlib only, tests mock every network edge, NO live queue write (batch 8 owns the queue file; this card reads it for a dry run only).

1. job/fit.py + CLI. For every `queued` row in build_order: verdict fit | no-fit | dead, plus a reason.
   Inputs: ce_directories category (+ dead flag), the playbook file text (Obsidian playbooks/build/<domain>.md, optional), one homepage GET (injectable).
   Rules in order: KNOWN batch 7 table (here, infobel, activityhero, vivinavi, fyple, buildzoom, accountantfinder) -> ce_directories.dead -> homepage DNS/HTTP dead -> duplicate of an existing row (same brand label, other TLD) -> non-US/non-English (ccTLD, html lang, playbook text) -> kids-only / contractors-only / CPA-only / developer platform keyword gates on category + title + meta description + playbook -> fit.
   `--write` moves no-fit/dead rows to `rejected` through transitions.record_transition with the reason. Not run on this card. Default is the dry-run table.
2. vaultwarden-cli-fill.js (citation-submitter profile skill): target pick = visible page whose URL matches (focused/first), not "exactly one page"; field = first visible match instead of exactly one. Test with the existing vm + mock CDP harness.
3. mkpayload.js into the skill scripts with `--alnum` (from b7/mkpayload_alnum.js), plus a test.
4. readmail.js: fetch whole body (BODY.PEEK[TEXT], no <0.60000> cap), decode QP, extract links first, then print the body up to a larger cap. Test with a long fixture (pure function split out from IMAP I/O).
5. count_capsolver_builds.py: WRITE it (job/count_capsolver_builds.py): balance before/after input + per-row solve log (JSONL) -> spend table. No network by default; balance arguments or log file.
6. CapSolver image hint: ImageToTextTask documents only `module` (common | number) and `websiteURL`; no length/charset parameter. So: no CLI hint. The build skill stops after 1 image solve and records needs-human. (CLI `--extra '{"module":"number"}'` already passes through for numeric captchas.) No spend, so no live test.
7. transitions.py: `claimed-unverified` state (found, claimed, edits ID-gated). queued|found|needs-human -> claimed-unverified; claimed-unverified -> live|rejected|needs-human|same-state note. Portal mapping: needs-human (client sees an internal wait, like found). Internal: no Activities row. Directories sync accepts it. Migration db/005: widen ce_directory_status.queue_state check (additive, same pattern as 004). Applied to prod BEFORE merge if a token is available; otherwise say so.
8. Patch citation-submit skill for 2-7.
