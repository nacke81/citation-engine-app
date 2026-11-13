# Plan: a visible street must not suppress the same entity's structured city/state/ZIP (t_69102cc9)

Cites lesson `docs/lessons/2026-11-13-age-is-not-death-ask-the-owner.md` (latest): read the owner's own signal before acting on a proxy. Here the proxy is "the page text shows a street, so structured data is never consulted"; the page's own JSON-LD (the owner's signal for that business) is consulted for the locality the text does not show.

## Proven from the live page (before any code change)
One guarded known-permalink read (`recheck.py --queue <COPY> --row create-nextdoor --any-state --save-pages`, dry run, through sitegate) saved the Nextdoor page. `--replay` of that page on origin/main 9e22692 gives `nap-incomplete address`, NAP read = `name | street | phone`. The page's `application/ld+json` LocalBusiness (name = canonical name) carries a full PostalAddress (street / city / KY / ZIP) that equals the canonical NAP, while the visible text shows the street only. (Real identity values are kept out of the repo; they are in the evidence capture.) Cause confirmed: `got = street_in(block)` is truthy, so `structured_address` (recheck.py ~L598) never runs.

## Change (job/recheck.py only, plus tests)
1. `structured_address(html_, name, same_entity=False)`: with `same_entity=True` only a JSON-LD block whose enclosing entity name equals the canonical name (`exact_name`) is returned. No LocalBusiness fallback, no Organization, no `*-selector` fallback. Default behaviour unchanged.
2. `compare()`: when the visible street matched the canonical street and the locality is genuinely missing (the existing `address` gap from `no_city` / missing state / missing zip), look up the same-entity structured address. Supplement only when its street equals the canonical street (`street_equal`). Then run the same city/state/zip checks the structured path uses; a wrong structured value is a `mismatch`. Any locality fragment the page does show (zip on the street line, state token) must also equal canonical, else `mismatch` (visible wins; JSON-LD never overrides a wrong visible value). The NAP string quotes the street and the structured city/state/zip.
3. Rendered-poll stability call (recheck.py L211) passes the page HTML so the poll and the final compare use one comparator. Proof (`proof.recheck_verdict` -> `read_listing` -> `compare`) is unchanged: one comparator.
4. No SCC / Nextdoor / Directory names in code.

## Tests (tests/nap_structured_locality_test.py, wired into CI)
- Real captured page (sanitized to the test identity, tests/fixtures/nextdoor-live-shape-20261113.html, built from the live capture; the repo may not hold the real identity, leak_check): match with full NAP.
- Same text without html: nap-incomplete.
- Wrong structured city / state / zip: mismatch.
- Visible wrong street with correct JSON-LD: mismatch.
- Visible wrong locality fragment with correct JSON-LD: mismatch.
- Unrelated entity / directory HQ (Organization, different-name LocalBusiness) address: cannot complete; stays nap-incomplete.
- JSON-LD street differs from canonical while visible street matches: no supplement.
- Proof path: proof_step moves iff recheck compare says match, on the real-shape page.
- Mutation: with supplementation removed, the real-shape regression fails (test runs compare with the supplement hook disabled and asserts it flips).

## Replay evidence (no network)
Latest saved live-row pages (existing --save-pages dirs / the Nextdoor capture) replayed on a queue COPY with main and with the branch; full diff of verdicts and NAP strings; sha256 of the real queue before and after.

## Out of scope
No deploy, no merge, no --write against the real queue, no portal write, no new recheck/QA card (QA t_ebbedd02 exists).
