# Plan: portal SCC live count follows the counting basis (t_9d36198a)

Cites lesson `docs/lessons/2026-11-15-quote-the-page-not-the-button.md` (latest at start): a claim needs evidence of the state it names. Here, "live" must mean live with engine proof, not "the scan saw a page".

## Read-only finding (prod, 11/16)
Portal snapshot SCC 2026-11-16 summary: live 26. Prod `ce_directory_status` SCC queue_state=live: 23 rows, all with proof_url + proof_nap_match true.
The 3 extra: `google.com` (GBP, scan found, no queue row, counts by Nate basis), `maps.apple.com` (scan found, no queue row, no proof), `n49.com` (scan found, no queue row, no proof). Cause: `snapshot.summary_from_rows` counts every row with state "live", and `portal.STATE` maps scan "found" -> "live".
Expected count: 23 + GBP = 24 (CONTRACT).

## Rule
A row counts toward `summary.live` only if (a) complete proof (`transitions.proof_problems` empty: permalink http(s) proof_url, proof_nap, proof_at, proof_nap_match true, build_action) or (b) it is google.com (GBP), once. Lead-gen/referral never count (no proof, so excluded). napCorrect / napChecked count over counted rows only.

## Change
- `job/snapshot.py`: `apply_count_basis(payload, proof_by_dir)` sets `countsAsLive` on live rows; `summary_from_rows` counts only rows with `countsAsLive is not False` (default unchanged for rows without the flag, so existing goldens hold).
- `job/portal.py` write_run (SCC only): after overlay, load proof via `transitions.db_proof_by_directory()` (read-only GET; sink off -> queue row `proof`), apply, recount. Failure to read proof refuses the SCC write (never publish an unproven number).
- Row state is left as-is; only the summary number and the extra `countsAsLive` field change.
- Test `tests/snapshot_count_basis_test.py`: pins 26 -> 24 with a fixture of the above shape, GBP once, unproven excluded, proof-incomplete excluded, no flag = old behaviour.

## After merge
Run the portal push, read back the portal snapshot summary, post it on the card.

## Rework (review round 1, comment 792)
The page counts state == live rows; summary/countsAsLive are dropped by the portal normalizer. Change of design:
- `snapshot.apply_count_basis` re-states every non-GBP live row without complete proof to couldnt_check / reason unproven / reasonText "Listing seen, not yet verified" (url kept, NAP cleared), keeps google.com once, recounts summary. No `countsAsLive` flag; `summary_from_rows` back to plain state == live.
- `portal.write_run(..., proof_by_dir=None)` and `run.portal_publish(..., proof_by_dir=None)`: injectable proof source; None reads ce_directory_status, failure -> PortalWriteError "proof read failed: ..." (logged PORTAL WRITE FAILED, old snapshot stays). Tests pass `proof_by_dir={}` and never read prod.
- `snapshot_dry_run` applies the basis (queue-row proof only, says so) or prints that it was not applied.
- Test asserts state == live rows == 24 on the written payload, GBP twice, proof-read failure text, dry-run parity. CI step added. maps.apple.com / n49.com proof is t_43aa1480, not here.
