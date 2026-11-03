# 2026-11-03 Proof gate on recheck's comparator (t_5871cdf9)

Cites latest lesson: docs/lessons/2026-10-30-park-on-a-human-only-after-an-agent-saw-the-step.md (a gate must check what the page shows, not the row's own fields).

## Why
11/01 weekly: PROOF moved create-nextdoor live on name+street+phone (no city/state/zip); RECHECK in the same run said nap-incomplete. proof.verdict() is looser than recheck.compare(); the looser one won.

## Change
- `proof.proof_step(..., reader=None)`: after verdict()=="match", re-read the SAME proof_url via `recheck.read_listing` (the one read+compare path) and require compare verdict "match" (full name/street/city/state/zip/phone). Anything else (nap-incomplete, not-public, unreadable, mismatch, read error) -> untouched, nothing written (mismatch from recheck is not written as proof_nap_match=false either; keep the None branch).
- Proof columns use the comparator's NAP. Default reader: signed-out Chrome via recheck.SignedOutReader, closed after the step. GET only.
- Tests: partial NAP (no city/state/zip) moves nothing; full match moves; PROOF and RECHECK share the comparator so cannot disagree. Existing suite stays green (inject reader).
- Ops (after merge, separate from code): back up queue .bak-proofgate, demote create-nextdoor via record_transition, clear Proof columns, read-only fix-bing check.
