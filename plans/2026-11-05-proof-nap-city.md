# Plan: proof_nap quotes the city/state/zip line (t_f2bc28d2)

Cites docs/lessons/2026-11-04-every-park-path-names-its-own-reason.md: grep every copy of the shape. nap is built once, at the end of compare() in job/recheck.py.

- When the street and the city/state/zip are on separate lines, street_txt = street, then segs (and a leading zip). Display only; verdict, wrong and gaps are untouched.
- Tests (tests/proof_nap_city_test.py, added to CI): two-line shape asserts city, state, zip in nap and same verdict; one-line control nap unchanged. Placeholder identities only.
- Offline. No queue writes.
