# Plan: Verify Now auto-allowlist on park (t_f31e2490)

Cites lesson `docs/lessons/2026-11-12-an-agent-gets-a-narrow-helper-and-a-clock.md` (latest by commit order): the agent path gets only narrow helpers, so the one transition that already knows the facts (directory, channel, tenant, vault item) owns the allowlist add; no manual step, no new actor.

Writer found (grep): `job/transitions.py` `record_transition`, step 3b (`ver.call("POST", VERIFY_UPSERT_PATH, ...)`), the only writer of a requires_verification `citation_verification` row.

Scope:
1. `job/verify_allowlist.py`: `auto_add(...)`. Only sms / phone-call. Adds `{domain, channels:[type], send:agent, signin_url, vault_items:{tenant:item}, added_by:auto, row_id, added_on}` to the runtime file `%LOCALAPPDATA%/citation-engine/verify_directories.local.json` (env `CE_VERIFY_DIRECTORIES_LOCAL` overrides). No-op if the directory (domain or alias) is already listed anywhere. Refuses any path inside the repo. Atomic write.
2. `verify_bridge.load_directories` merges repo file + local file; repo wins on any domain/alias overlap; local entries are forced `send=agent`. Explicit `path=` or `CE_VERIFY_DIRECTORIES` without a local env = repo file only (hermetic tests).
3. Hook in `record_transition` right after the portal verification row write succeeds (not on dry run; dry run reports `allowlist_request`). Failure appends to `errors`, never blocks. New `--vault-item` flag (the item the build run used); absent = convention `<TENANT> - <directory>`, reported as defaulted.
4. `verify_bridge.py --check` prints both sources and counts.
5. Tests `tests/verify_allowlist_test.py` + CI step.
No live session, no portal write outside tests, no send.

## Round 2 (review changes_requested, Nate)
The bridge matches domain AND channel and the send needs vault_items[tenant], so "domain listed" is not done. auto_add now: new entry if unlisted; MERGES the missing channel / tenant item into a LOCAL entry; for a REPO send=agent entry writes a local supplement row (repo file untouched) that load_directories merges (repo values win, send stays the repo send); a repo send=script entry is never extended. --check prints supplements. Tests 13a-13l: sms-only repo entry + phone-call park, NM then SCC on one new directory, repeats add nothing, script entry untouched, repo fixture byte-identical. Main (d03c11c) merged.
