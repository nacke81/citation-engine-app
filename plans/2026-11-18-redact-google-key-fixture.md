# Plan: redact the third-party Google key from the localstar fixture + a save-time scrub (t_6df6203a)

Cites lesson `docs/lessons/2026-11-18-a-prompt-check-must-not-read-the-host.md` (latest at start): a check must not depend on what the host happens to hold. Here the "is it ours?" answer must not rest on a guess, and the guard must read the fixture tree itself, not a list we maintain.

## Finding
GitHub secret-scanning alert #1 (google_api_key, publicly_leaked) points at `tests/fixtures/localstar-scc-20261118.html` line 740: `<script src="https://maps.google.com/maps/api/js?...&key=AIza...">`. That is localstar's own embedded browser Maps/Places key in the saved third-party page. No `AIza` string exists in any `.env*` / config under the sibling repos or this repo. (Hermes `.env` files were not readable from this seat: the harness blocks them; flagged in the handoff.)

## Change
- Fixture: replace the key with `REDACTED_GOOGLE_KEY` (one line; the test only reads the Full Address row and keeps the map script line).
- `tests/fixture_scrub.py`: `scrub(text)` strips `AIza[0-9A-Za-z_-]{35}` -> `REDACTED_GOOGLE_KEY`; CLI `python tests/fixture_scrub.py FILE...` scrubs saved HTML in place (the step to run after saving a page).
- `tests/fixture_scrub_test.py` (+ CI step): scrub removes keys (incl. two on a line, URL-encoded context, `&amp;` context), is idempotent, leaves non-keys alone (short `AIza`, 34 chars); CLI rewrites a temp file; and a guard walks every file under `tests/fixtures/` and fails on any `AIza` key. Mutation: put a key back in a temp copy -> guard function fails.

## Proof
Full `localstar_full_address_test.py` and the new test pass; `grep AIza` over the tree is empty. Then PR, merge under the standing rule, dismiss alert #1 `used_in_tests`, read back state.

## Round 2 (review changes_requested; cites lesson `docs/lessons/2026-11-18-two-sources-one-page-must-agree.md`: one check is not enough when a second path can disagree)
The CI guard fires only after a push, and a push to this public repo already publishes the key. Close both pre-push paths:
- `tests/leak_check.py` (the pre-push check agents run): Google-key shape built from split strings, applied by `scan_text` to every file in the whole-repo walk, plus a runtime-assembled planted control that must be caught.
- `fixture_scrub.write_fixture()` is the single write path; `build_fixtures.py` and `build_resolver_fixtures.py` call it, so a saved key is scrubbed before it reaches disk.
- Tests (in `fixture_scrub_test.py`): W1 helper lands 0 keys, W2 builders use only the helper, W3 detector mutation, L1/L2 leak_check clean/whole-repo, L3 mutation (shape removed -> planted control FAILS). G1/G2 and the CI step are unchanged.
- Proof: new leak_check on origin/main FAILS (real key in the fixture); on head PASSES.
