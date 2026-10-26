# Plan 2026-10-26: recheck phone parser (kanban t_032083dc)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-26-batch9-fixes.md. Applied: stdlib only, fixtures not network in CI, exact-name strictness kept, no Directory write. (Plan file written after the first source edit; noted in the handoff.)

1. `recheck.phones_in`: a phone needs non-alphanumeric boundaries and is not read from an id/uuid/hash token (hotfrog "Verified ID: 0099...-7780175522c0").
2. Structured data first: `structured_phones(html)` reads tel: hrefs, JSON-LD telephone, itemprop; `Page.html` carries the raw HTML (plain and Chrome).
3. Masked phone (`+127****2550`) is partial: `masked_match` compares visible leading/trailing digits to canonical; agree -> `match (masked)`, disagree -> mismatch phone, hidden ("Reveal phone") stays a gap.
4. `read_block`: when the exact name appears several times (freelistingusa breadcrumb), take the occurrence whose block carries the NAP, reading past the "Claim this listing" panel.
5. Foursquare: page itself shows `+27 84 125 50`; mismatch is the true reading, test pins it.
6. Tests: tests/recheck_phone_test.py + fixtures tests/fixtures/recheck/ (saved real pages); CI step added; recheck_test R8b updated.
