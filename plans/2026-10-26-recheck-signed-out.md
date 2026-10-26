# Plan 2026-10-26: recheck reads signed out (kanban t_ac8b1bdd)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-26-recheck-phone-parser.md (its false live on fix-bing is the reason for this card).

1. `recheck.chrome_fetch`: read in `browser.new_context()` (fresh, signed out), closed after. Never `contexts[0]` (the signed-in build profile).
2. A fresh context that is walled is a wall: `get_page` never falls back to the profile, so the verdict is unreadable/gap, never match.
3. Other `contexts[0]` readers audited: `claim_reread.chrome_reader` moved to a fresh context (read-only claim status). `build_proof.py` only classifies wall behaviour of the build profile and decides no live state: left as is. `build_runner`, `discover`, `mapnap` are build/discovery steps: left as is.
4. Test tests/recheck_signedout_test.py (CI step): stub browser, profile context shows canonical phone, fresh context shows 918-4885 -> `mismatch phone`, row not live; contexts[0] never used; fresh context closed; wall in fresh context -> unreadable.
5. Chrome-route matches must repeat on STABLE_READS=3 fresh signed-out reads: Bing Maps served 841-2550 on 2 of 10 signed-out reads (the dry run flipped between match and mismatch).
