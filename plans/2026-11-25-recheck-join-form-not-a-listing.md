# Plan: recheck must not read a join/submit form as the listing (t_f169b3d6)

Builds on lesson `docs/lessons/2026-11-24-a-second-business-must-not-borrow-the-first-ones-proof.md` (latest at start): a gate that passes the wrong thing writes a wrong verdict. Here the gate (`_is_entry_page`) passed a form and `not_public()` wrote a verdict from a blind read.

Branch `citation-engineer/t_f169b3d6`, fresh clone of origin/main. The live queue is never touched; tests use temp copies.

## Facts (read, not assumed)
- `ENTRY_RE` has no `join`; `listing.PERMALINK` has no us-business.info shape, so `/join/` passes both gates.
- Signed-out GET `https://us-business.info/search/?q=<name>` returns 200 with server-rendered cards `<a href="/company/<id>/"><h3>name</h3>`. q="Walmart" returns other businesses; q="Senior Care Consulting & Solutions" returns the SCC card first. The site has a public search.

## Items
1. `ENTRY_RE`: add `join`.
2. `listing.PERMALINK["us-business.info"]` = `^/company/<id>`: `/join/`, `/search/`, `/directory/<st>/` are not permalinks.
3. `RECHECK_SEARCH["us-business.info"]` -> `/search/?q=<name>`, so a form-only row takes the search path.
4. Tests in `tests/recheck_test.py`: (a) `/join/` evidence_url -> `_permalink` None; (b) a `/company/<id>/` URL still passes; (c) a join-only row fetches the search, never the form; card found -> reads the card; no card on a readable search -> not-public from the SEARCH; a Directory with a form URL and no search -> `no-permalink` + no-URL backoff, form never fetched.
