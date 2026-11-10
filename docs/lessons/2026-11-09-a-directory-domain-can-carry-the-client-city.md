# Lesson: a Directory's own domain can carry the client's identity token (t_9736bbe4)

Cite: `plans/2026-11-09-scc-new-directory-rows.md`.

The first draft keyed a USA Online Network row by its city host, and `tests/leak_check.py` failed: the client's city is a denylisted identity token, and a Directory domain, a seed row and a migration all repeat it. The fix is to key the row by the network's own domain (the host that serves the claim form), not a city or client-specific subdomain.

Rule: before adding a Catalog row, pick the domain that owns the submit form, and run `tests/leak_check.py` right after the first seed regeneration, not at the end. Also: the hunt table's "free" claims were only search snippets for half the rows; two of them (a $9/mo package page, an advertise-with-us lead form) were paid when I fetched the add page. Fetch the add path itself before promoting.
