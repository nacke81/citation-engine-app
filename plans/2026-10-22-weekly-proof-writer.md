# Plan 2026-10-22: weekly job writes Proof (kanban t_f081c9ba)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-22-builder-stat-cards.md, which says the Proof columns are additive (migration 003, applied in prod before PR #14) and "the job (writer of proof columns) is not changed". This plan is that job change. Applied lesson from that plan: read only what the DB really stores; the result cards must never over-count. Base: origin/main f79679b.

## Design
New job/proof.py, `proof_step(checks, day, ...)`, called from run.py main() after directories_step (status rows exist) and non-fatal like the other steps.

Inputs are THIS run's `checks` only (the list `build()` just produced). Nothing is read from earlier runs or from stored proof columns, so no Proof carries over.

For each SCC check whose Directory has a queue row in state submitted / pending-verify / needs-human (queue file read, never written here except through transitions.py):
- result `found`, a listing permalink URL (listing.is_permalink), name+street+phone all matched, and no diffs -> MATCH:
  1. upsert ce_directory_status: proof_url, proof_nap (the NAP the page showed), proof_at (now, UTC), proof_nap_match=true, build_action.
  2. then transitions.record_transition(... "live", evidence=proof_url). Proof is written BEFORE the transition: if the transition fails the row stays waiting and the next run retries; the reverse order could strand a live row with no Proof. record_transition also fires the client-voiced Activities row (default on, held by approved_at null).
- result `found` but NAP differs (or any diff) -> MISMATCH: upsert proof_nap_match=false and null proof_url/proof_nap/proof_at/build_action (clears any older Proof). State untouched.
- anything else (couldn't check, absent, unsearchable, found with no permalink): write nothing.

build_action: queue_kind create -> new; fix row with this run's claim_status claimed and no wrong_field -> claim; otherwise fix. An explicit queue_kind claim -> claim.

No Directory writes, no submits: the module only consumes check results already gathered by the read-only discovery. No migration needed (003 columns exist); nothing to apply.

## Golden tests (tests/proof_test.py, added to CI)
G1 submitted + matching re-check -> queue live, status row has all Proof, counts as a result under the page's rule (live + url + nap + at + match true + action); Activities row written.
G2 submitted + mismatch -> stays submitted, proof_nap_match=false, not a result, no transition, no Activities.
G3 couldn't check -> no write at all (db calls empty, queue file bytes unchanged).
Also: pending-verify and needs-human move; live/queued/rejected rows are ignored; no carried-over Proof (stale full Proof then mismatch is cleared); create->new; no network (urlopen patched to raise); NM checks ignored.

## Out of scope
Directory traffic, submits, portal seed, page changes, migrations.

## Round 2 amendment (2026-10-22, review comment 289)
Latest lesson read: none exist (no docs/lessons). Fixes: (1) verdict() needs a non-blank nap_shown for a match, else writes nothing; (2) run.py calls the Proof step only when ok_run is true (proof_step_if_ok), printing "PROOF SKIPPED: run failed guards" otherwise; (3) nit: every waiting row on a Directory moves, not just the first. Tests added for all three. Nit not done: preferring texts[lurl] for proof_nap needs page text that proof_step never sees (it only gets checks); left for a follow-up.
