# Plan: a complete "Full Address" row beats a partial Address Details block (t_59f339e5)

Cites lesson `docs/lessons/2026-11-17-creds-outside-the-env-need-a-fence.md` (latest at start): a check that passes for the wrong reason hides the real path. Here the reader's "nap-incomplete" hid a page that does carry the whole address; the fix must not turn that into a looser match.

## Finding (base eb9e1b7, reproduced on the sanitized saved page)
Signed-out localstar page (listing URL from the create-localstar row): Address Details block = `street` + `city` only; Contact Details has `Name / <business> / Full Address / street, city, ST zip`. `recheck.compare` reads the block, street matches, city only -> `gaps=[address]` -> nap-incomplete (11/12, 11/18).

## Change
- `job/recheck.py compare()`: when the street matched but `address` is still a gap, look for a labelled `Full Address` row in the page text. Accept it only if the line above-ish (<=4 lines before) is the exact canonical business name (never another entity's row) and it parses as `street, city, ST|State zip`. Then every part is compared with the same rules as the structured path: street_equal, city_same, state, ZIP. Any difference -> mismatch (wrong=address/city/state/zip). A partial row, or an unreadable canonical state/ZIP, leaves the gap. Visible wrong locality already found under the street is never overridden (wrong non-empty -> no supplement).
- Fixture `tests/fixtures/localstar-scc-20261118.html`: the real signed-out page, sanitized to the test identity (Alder Care, 100 Example Dr, Exampleton KY 40000, 502-555-0101, example.com).
- `tests/localstar_full_address_test.py` (+ CI step): fixture match; wrong state / ZIP / city / street in the row -> mismatch; partial row -> nap-incomplete; row under another entity's name -> no supplement; Address Details only (row removed) -> still nap-incomplete; mutation check.

## Proof
Main-vs-head `recheck --include-live --no-chrome` dry run on a queue COPY, full output diffed incl NAP strings; only localstar may change. No queue write, no .env.
