# Plan: a new domain gets a Directory row by rule; --verify-link reads agency mail (t_9a722352)

Cites lesson `docs/lessons/2026-11-13-one-source-for-the-steps.md` (latest): one place owns a fact. Here the fact "this domain is a Directory" is owned by ce_directories, and two callers (transitions sink, playbook set) each assumed another step had already put the row there.

Root cause (read from db/002_directories.sql line 52 and db/017): `ce_directory_status.directory` and `ce_directory_playbooks.domain` both REFERENCE ce_directories(domain). A park or playbook for a domain not in the Catalog (alignable, designrush, sortlist) violates the FK -> PostgREST 409. verification_written was already true because the queue and portal writes come first and the sink never blocks them.

Part 1 (job/directories.py, transitions.py, playbook.py):
- `directories.ensure_directory(db, domain, day)`: GET the row; if absent POST a minimal row {domain, name (first label, hyphens to spaces, title case), priority 4, category general, source 'auto', last_verified null} with on_conflict=domain + ignore-duplicates (never overwrites a real row). Bad domain -> DirectoriesError with a clear message.
- callers: `sync_transition` (every tenant, before the status upsert), `transitions.create_row` (non-dry-run, before the queue write; failure refuses with a clear message, nothing written), `playbook.set_playbook` (replaces the "add the Directory first" refusal; dry-run only reads and reports it would add).
- No change to the tenant lock or the fence.

Part 2 (job/mail_scan.py verify matcher): from the real relay rows. Sortlist's CTA is on short host sortli.st and the old matcher returned a SendGrid click-tracker link (random path matched `key|code`) instead. Clutch's mail has a code and a HubSpot link host. Add per-directory link-host aliases, prefer them, drop /asm/ (unsubscribe group) links, keep code reading.

Tests: tests/auto_directory_test.py (fakes with FK semantics: POST status on unknown domain -> 409), both fixtures sanitized into tests/fixtures/verify-mail-*.json. Mutations: remove ensure -> FK fake 409s; remove alias -> sortlist test fails. CI step added.
No prod writes in this card. Afterwards (separate, post-merge): set sortlist.com and designrush.com playbooks.
