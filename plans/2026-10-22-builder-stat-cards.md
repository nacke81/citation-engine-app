# Plan 2026-10-22: builder stat cards + Checked stat (kanban t_eef79f15)

Latest lesson read: docs/lessons/2026-10-07-lis-vaultwarden-default-env-resolution.md (v1 repo, this repo has no docs/lessons). Applied: resolve environment from the real source, never assume. Here: the page reads only what the DB really stores, and any column it needs is added by an additive migration applied BEFORE merge (portal PR #54 lesson). Prior plan: plans/2026-10-19-scc-queue-portal-submit.md. Base: origin/main 7f73262.

## Data inspection (read-only, 2026-10-22, live project)
- ce_directories: 86 rows. ce_checks latest run cf6e2f6d (10/18): 25 per business. SCC 11 found (5 with diffs), 13 couldn't check, 1 unsearchable. NM 11 found (9 with diffs), 1 not found, 12 couldn't check, 1 unsearchable.
- ce_directory_status: 6 rows, all SCC (bing submitted/fix; mapquest, yellowpages, superpages, dexknows needs-human/fix; 1 needs-human/create). NM has 0 rows. last_result and claim_status are null on all rows (the job has not written them yet), so the page takes the finder half from ce_checks, as today.
- queue file (local): 5 fix rows, all Mike-approved, no create rows.

| Builder state | In data today? |
|---|---|
| To build | Derivable from ce_checks (diffs, not found, found+not claimed). No stored column needed. |
| Waiting on directory | Exists: queue_state submitted / pending-verify. |
| Needs a person | Exists: queue_state needs-human, plus agent_access=blocked rows with no state. |
| New listings live / Claimed / Fixed | NOT derivable: queue_state=live has no Proof fields and no way to say new vs claim vs fix (queue_kind only fix/create, no claim). Needs new nullable columns. |

## Migration db/003_builder_proof.sql (additive, nullable, idempotent)
ce_directory_status gains: build_action text (new|claim|fix), proof_url text, proof_nap text, proof_at timestamptz, proof_nap_match boolean. The view ce_directory_biz is replaced with the same columns plus these five at the end. No default, no backfill, no NOT NULL. Page tolerates the columns being absent (treated as no Proof, so result cards read 0, never over-count).

## State machine (one state per business x Directory row)
Finder facts: not found, found with NAP errors (diffs), found correct, couldn't check. Owned = claim_status == 'claimed'.
Candidate action (derived, never hand entered), first match wins: found with errors -> fix; found and not owned (correct or not) -> claim; not found -> new; else none. Couldn't check -> none.
State, first match wins:
1. queue_state live AND Proof complete (http(s) proof_url, proof_nap, proof_at, proof_nap_match === true) -> result card for its action (build_action, else queue_kind fix->fix, create->new, else derived candidate).
2. queue_state live without Proof -> waiting (never a result).
3. queue_state submitted | pending-verify -> waiting.
4. queue_state needs-human, or (no state/queued and Directory agent_access blocked) -> needs a person.
5. queue_state rejected -> none (shown in neither; follow-up is a human decision).
6. candidate action exists -> to build (breakdown new/claim/fix).
7. otherwise none.
Claimed is independent of Correct: a correct unclaimed listing is a claim candidate; a claimed listing with errors is a fix candidate.
"Approved" in To build: the DB stores no approval, so To build = derived candidates not yet started. Flagged for Nate.

## Checked
Directories in the latest run for that business (25) of ce_directories count (86). If the Directory table cannot load the "of N" is omitted.

## Tests (golden, with code) tests/builder.test.mjs
G-proof: submit alone, live without Proof, live with Proof but NAP mismatch -> waiting, not a result; live with full Proof -> result.
G-queue: errors -> fix, not found -> new, found unowned (incl. correct) -> claim, claimed with errors -> fix, claimed correct -> none, couldn't check -> none; no hand entry.
Also: one state per row (sum of all cards <= rows), counts derive from rows (changing a row changes the count), Checked "25 of 86", markup has the 9 stat labels per business, CSS has no break-all inside .stat, migration shape (additive, nullable, no secret).

## Out of scope
Any submit/claim/write, portal, t_d43f9e55. The job (writer of proof columns) is not changed; with no proof rows written the result cards read 0 honestly.
