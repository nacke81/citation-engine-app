# A form URL is not a listing, and a blind read is not a verdict

us-business.info `/join/` is the submit form. `recheck._permalink` passed it because the entry-page gate was a deny-list (`ENTRY_RE`) with no `join`, and the Directory had no allow-list shape in `listing.PERMALINK`. Every recheck then read the form, found no business on it, and `not_public()` wrote "no listing" plus a 2-day backoff: a verdict from a page that could never have shown the listing.

Rules:
- A deny-list of form words always has a missing word. Give each Directory we recheck a positive listing shape (`PERMALINK`) so a form fails by default.
- A "not public" verdict is only valid when the page read could have shown the listing. A search page that rendered and lacks the business qualifies; a form page does not.
- Test the whole row path (form-only row -> search / no-URL backoff), not just the predicate, and run the tests against the unfixed code to see them fail.
