# Plan 2026-10-16: weekly job writes SCC + NM citation-engine snapshots to the portal (kanban t_c4bc4eb7)

Latest lesson read: none exists (docs/lessons absent in this repo; v1 repo's docs/lessons holds only README.md). Prior plan: plans/2026-10-16-gate4-changes.md (a2b2779). Base: origin/main a2b2779. Mike approved the portal write 2026-10-16; Nate chose key option (a) and the base (comment thread on the card).

## Decisions
- Writer is Python (`job/portal.py`), because the job is Python. It upserts into portal `footprint_snapshot` over PostgREST with `on_conflict=client_id,source,captured_day`, the same key as the TS `upsertFootprintSnapshot`. No new schema.
- Allow-list in code: SCC `e1fb5abd-8d7f-4d83-8cde-18934d149bb5` (prod lookup by slug, read-only, cited in handoff), NM `fe3062b5-c956-4358-9e77-840e18be9f85`. Explicit FORBIDDEN ids 430b764e-... (FBS) and 7caf0d65-.... Any id outside the allow-list raises BEFORE any network call. The write path is `biz -> id` only; no caller-supplied id.
- Key read in place from the portal repo `.env.prod.local` (path in a local pointer file) (NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY only). Never copied, printed, logged. Error text is scrubbed of the key.
- Payload from ce_checks rows: `found` = result found; `correct` = found with no fix-list diffs; `withNapErrors` = found with diffs (found = correct + withNapErrors); `notFound` = absent; `couldntCheck` = couldnt_check + unsearchable (new optional field). `keyScore` null. `pctFound` = found/(found+notFound) as the existing contract. Directory row for all 25 Catalog Directories: domain, url, napConsistent (found and no diffs), issues (diff fields; `site` -> `website`), status (found -> nap, absent -> undiscovered, couldnt_check -> blocked/unavailable by note, unsearchable -> unavailable).
- Run flow: build-DB write first and unchanged. Then portal write inside try/except. On failure: print `PORTAL WRITE FAILED` to the run log, exit 1, build-DB rows already committed. `--dry` never writes either.
- Backfill: `python job/run.py --portal-backfill <build-DB run id>` reads that run's ce_checks and writes the two rows. Used once for run 20261016-1444 (id 4b31adea-...).
- Portal repo (fresh worktree off origin/master): type gets optional `couldntCheck`; engine provenance becomes "Listings checked <date> by <agency, per card>"; engine stats show Found, Correct, NAP errors, Not found, Couldn't check; table shows NAP consistent/fix issues. BrightLocal wording stays only for the brightlocal source. The TS NM-only seed script is left as is (not the weekly path).

## Tests (written with the code)
- Python (tests/portal_test.py, run in CI): counts equal build counts for the 1444-shaped fixture (SCC 11=6+5,0,14; NM 11=2+9,1,13); FBS ids and a random id refused with zero network calls; biz not SCC/NM refused; failure in portal write leaves exit 1 and build rows written (fake DB records call order); key never in error text; no Directory or portal-seed call in the non-production path.
- Portal vitest: provenance line exact, no BrightLocal; engine block renders the new stats.

## Not done / limits
- Reviewer must fast-forward the runtime clone after merge, before Sun 10/18 11:00.
