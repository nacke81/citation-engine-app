# Plan 2026-10-27: Moz _post sends a real User-Agent (kanban t_10480049)

Latest lesson read: docs/lessons/2026-10-27-test-the-rule-on-real-row-shapes.md (test the rule on the real shape). Here: the test drives the real `_post` and inspects the Request urllib actually receives, not a copy of the header string. Prior plan: plans/2026-10-27-moz-domain-authority.md.

Defect: Cloudflare answers error 1010 to the default `Python-urllib/x.y` User-Agent; `quota.lookup` fails closed, 0 rows fetched.

Steps
1. `job/moz.py`: module constant `USER_AGENT = the card UA string, split in source for the leak check`; `_post` adds it to headers. Nothing else changes.
2. `tests/moz_test.py`: patch `urllib.request.urlopen`, call `_post`, assert the Request's User-Agent equals the constant and is not `Python-urllib`; token still only in x-moz-token. No network.
3. Grep other `urllib.request.Request` calls without a UA; list in handoff, no changes.
