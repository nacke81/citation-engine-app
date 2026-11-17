# Plan: pin DB-proof precedence in count_proof (t_be2150cd)

Cites lesson `docs/lessons/2026-11-17-count-it-but-do-not-claim-it.md` (latest at start): the count must follow proof, so a test must show proof from each source is honoured.

## Gap
Mutation of `job/portal.py count_proof` (`if not T.proof_problems(v): proof[k] = v` -> `pass`) passes the whole suite. A live queue row with no `proof` key (pre-guard row) whose proof is only in ce_directory_status would be re-stated to couldnt_check on the client page.

## Change (tests only, plus one guard)
- `tests/snapshot_count_basis_test.py`: through `write_run(..., proof_by_dir={dom: complete proof})` with the queue live row lacking `proof`: written row stays `live`, count 24. Also: incomplete DB proof does not override a complete queue proof; incomplete DB proof with no queue proof is re-stated. Direct `count_proof` asserts. `proof_by_dir` always explicit, never prod.
- Re-run the mutation; it must fail.
- `tests/snapshot_test.py`: set CE_DIRECTORIES_WRITE=0 at the top (see finding).

## Prod finding (read-only)
Prod ce_directory_status SCC has `a.example` (fix-a, pending-verify, 2026-10-26) and `b.example` (fix-b, submitted). Writer: `tests/snapshot_test.py` S3/S4 (`record_transition` without `directories=`, sink not off -> `D.DirDB()` prod when run locally with prod env; CI has none). Removal is a prod delete: needs-mike.

## Round 2 (changes requested): permanent guard + full read-only inventory

Cites the same lesson (`docs/lessons/2026-11-17-count-it-but-do-not-claim-it.md`, still the latest).

### Why the first fix was not enough
`directories.DirDB()` reads its creds from `%LOCALAPPDATA%/hermes/.env`, not the process env. Any LOCAL test run that reaches the Directory sink with `CE_DIRECTORIES_WRITE` unset writes prod; CI has no creds so it never showed. Writers found: `snapshot_test` (a.example, b.example), `batch13_test` L241 (a.example), `batch22_test` `record()` (dnb.com, discoverourtown.com). 36 test files imported sink modules with no flag at all.

### Change
- `tests/no_prod_directory_sink_test.py` (new, in CI): ast scan of every `tests/*.py`. A file that imports transitions/directories/recheck/buildrows/nm_transitions must set `os.environ["CE_DIRECTORIES_WRITE"] = "0"` before that import and never set another value. On-purpose "1" files (mirror_proof_test, recheck_promote_test, directories_test): flag set before the import, and every record_transition/record_existing/record_proof/create_row/mirror_proof_quiet/sync_* call made while the flag is not "0" must pass a non-None `directories=`/`db=`. 8 synthetic negative paths test the scanner itself.
- Flag "0" added at the top of 36 test files (batch13/batch22 among them). `directories_test` now sets "1" on purpose at the top; its D4 pop became "1" and its dry-run call passes a fake.
- Base main: the scan fails with 33 offenders, naming batch13_test.py, batch22_test.py and snapshot_test.py. Head: 9/9.

### Read-only inventory (GET only; no cleanup in this card, child t_27a61d85)
| where | key | writer | repair |
|---|---|---|---|
| prod `ce_directory_status` (SCC) | id 5566e18e-6024-44bd-91a7-5fe94559ed8f, a.example, fix-a, pending-verify, 2026-10-26, proof_url https://a.example/listing/1 | `snapshot_test` S3/S4 (and `batch13_test` L241, fix-a -> submitted) via `record_transition` -> `D.sync_transition` | delete |
| prod `ce_directory_status` (SCC) | id a3c77827-6d2e-482a-9e80-9926f5550c1d, b.example, fix-b, submitted, 2026-10-26 | `snapshot_test` S1/S2 | delete |
| prod `ce_directory_status` (SCC) | id f939b348-2926-4adf-8bb1-9a30009acca0, dnb.com, row create-dnb, `found` 2026-10-28 | `batch22_test` `record()` -> `R.recheck(record=...)` with no `directories=` (introduced #55, 28fe5c7); queue says needs-human | re-sync from the queue (upsert queue_state needs-human; not delete: real directory) |
| prod `ce_directory_status` (SCC) | id 05bb4497-6213-41d7-81b7-22574ebf744a, discoverourtown.com, row create-discoverourtown, `submitted` 2026-10-28 | `batch22_test` same | re-sync from the queue (needs-human) |
| prod `ce_directories` catalog | domain a.example (name "A", source auto, build_eligible true, build_route agent, updated_at 2026-11-14T00:42:36Z) | `D.ensure_directory` (directories.py:187 via `sync_transition`; ensure_directory added 2026-11-13 in 1b53244 #11x): first local test run after that commit, 11/13 18:42 CST | delete (after the ce_checks and status rows) |
| prod `ce_directories` catalog | domain b.example (name "B", same fields, 00:42:37Z) | same | delete |
| prod `ce_checks` | ids 93c845e6-edcb-4268-a5fb-1508d88dde6a (SCC a.example), 2d444a25-7817-40c8-bb41-d86bcc4ad0b7 (SCC b.example), defb3410-021f-4d0d-a112-422ca2b22d8a (NM a.example), 1133250e-e041-49cf-b302-8af1e401b360 (NM b.example); run 9c58984c-5ae0-477f-83aa-3beaf0869ada, 2026-11-15, couldnt_check/no-method | the weekly run walked the polluted catalog | delete (they reference the catalog domains) |
| live SCC queue `scc-fix-create-queue.json` | `/create_queue/rows/105` create-a (a.example, queued, found_on 2026-11-15, blanket Mike approval); `/create_queue/rows/106` create-b (b.example, same); `/build_order/84` "create-a" and `/build_order/88` "create-b" | `buildrows` promoted both from the polluted catalog (found_on 11/15). create-b was not in the first inventory | remove both rows and both build_order entries (backup first) |
| prod portal `footprint_snapshot` SCC (client e1fb5abd-8d7f-4d83-8cde-18934d149bb5), source citation_engine, captured_day 2026-11-16, 171 rows | directories rows a.example, b.example `blocked` (CLIENT-VISIBLE); dnb.com and discoverourtown.com also `blocked` (queue: needs-human, so consistent, not checked for client wording) | snapshot is rebuilt from catalog + queue | after catalog/queue repair, re-run the snapshot writer so those two rows drop out (171 -> 169); leave dnb/discoverourtown |
| prod portal `footprint_snapshot` NM (client fe3062b5-c956-4358-9e77-840e18be9f85), citation_engine, 2026-11-15, 171 rows | a.example, b.example `couldnt_check` (also dnb.com, discoverourtown.com couldnt_check, real directories, fine). The 2026-11-08 NM snapshot (148 rows) has only the two real ones. | same | re-run the NM snapshot after the catalog repair |
| `ce_directory_playbooks`, `ce_runs`, `ce_weekly_metrics`, `citation_verification`, `deliverables` | no `.example`, nowhere, fixture owner hits. (`deliverables` 1d1037e9... matched only the substring "1111" inside a vault hash: not a fixture) | none | none |
| NM queue `nm-fix-queue.json` | no `.example` rows | none | none |
| POSTCARD ALERT cards (nowhere.example) | `postcard_step_test` used the real hermes CLI before the tripwire; fixed in bff21e2 (2026-10-27, `CE_NO_CARDS`); the test now trips on any card argv | n/a | none (already guarded; closing the cards is Nate's) |

Rows `updated_at` for the status fixtures carry the fixture day (2026-10-26/28), so every unguarded local run rewrites them. Not found anywhere: ids starting `1111` in CE tables.

### Verification
Every `python tests/...` command in the workflow run with `CE_DIRECTORIES_WRITE=0` set explicitly: all pass except `verify_agent_test.py` (2 FAIL "prompt holds no code, no service key, no 6-digit run"), which fails identically on the prior commit with my changes stashed (local-env only; CI passed on #129) and touches no sink module.
