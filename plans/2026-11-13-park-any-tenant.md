# Plan: park works for any tenant, NM first (t_cb7bad04)

Cites lesson `docs/lessons/2026-11-13-first-found-must-not-hide-the-rest.md` (latest): a guard written for one case (`client != "SCC"` refuse) silently decided "no other tenant parks" for everything the SCC path does. Here the one decision is split into its real parts: which parts are tenant-specific (queue file, portal client id, row-id prefix, snapshot/activities sinks) and which are shared (verification row, allowlist, Your turn gate, Directory DB). Each part is read from one `TENANTS` config, so client 3 is a config line.

Problem: `transitions.py --client NM --to needs-human --verify-type phone-call` -> `REFUSED: queue transitions are SCC only`. nm_transitions.py writes the NM queue file only, so no Your turn row and no Verify Now allowlist entry. No command adds a row for a directory with no NM queue row.

Scope (job/transitions.py, job/nm_transitions.py comment, tests/park_any_tenant_test.py, CI step, lesson):
1. `TENANTS` config in transitions.py: key -> portal slug, queue file name + default path, row-id prefix, `snapshot` (SCC only: the NM queue has no portal snapshot), `activities` (SCC only), `create_row`. NM = slug (see TENANTS), `nm-fix-queue.json`, prefix `nm-`.
2. `record_transition` reads the tenant from `TENANTS` (unknown client refused). Tenant lock `check_tenant_lock` runs before any read/write: NM needs an `nm-` row id and the `nm-fix-queue.json` file; SCC refuses `nm-` rows. The verification row's client_id is asserted equal to the tenant's portal client id before the POST.
3. NM park: queue file (with `.bak-nm-<day>` backup, as nm_transitions does), verification upsert (same table/RPC as SCC), allowlist (resolve_for_domain, tenant key `NM`), Directory DB sync. Portal snapshot and client Activities are skipped for NM (reported as skipped, not an error).
4. `--create-row --domain D --kind create|fix` (NM): one queued row in the NM queue's `fix_queue`, id `nm-<kind>-<label>`, refuses an existing Directory, backup + atomic write, dry run prints the row. SCC points at buildrows.py.
5. nm_transitions.py is kept as is for build-run queue history (no portal). A park goes through transitions.py only, so nothing writes twice. buildqueue's NM path is unchanged.

Tests (offline, fakes): NM park writes queue + one verification row for the NM client id + allowlist entry with tenant NM; SCC park unchanged (existing tests); NM park can never write the SCC client id (lock), SCC park can never write an `nm-` row, wrong queue file refused; mutation of the lock must make the cross-tenant write happen (test shows it would fail); create-row writes exactly one row, refuses duplicate domain, dry run writes nothing; dry run prints the portal write.
No prod writes. Merge via Mike/merge-watch after review.
