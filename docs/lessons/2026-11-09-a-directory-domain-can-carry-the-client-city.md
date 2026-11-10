# Lesson: key a Directory row by the host that serves the listing permalink (t_9736bbe4)

Cite: `plans/2026-11-09-scc-new-directory-rows.md`.

The first draft keyed a USA Online Network row by its city host, and `tests/leak_check.py` failed: the client's city is a denylisted identity token, and a Directory domain, a seed row and a migration all repeat it. The fix then swapped to the host that serves the claim form (`usaonline.us`). That was also wrong: no listing lives there. Profiles live at `<city>.kentuckyonline.us/profile/...`, so the row could never be proven live.

Rule: key the row by the registrable domain that hosts the listing permalink (the proof host). A city subdomain under that domain is fine; the form host is irrelevant. The engine compares the listing host to the Directory domain in four places, and a wrong key fails all four:
- `recheck.resolve_by_search` (same host)
- `lookup.py:46` (host == directory)
- `mail_scan.host_ok` (host or subdomain)
- `your_turn_gate.py:53` (final_url host or subdomain)

Before adding a row, write down one example listing URL from a page you fetched and key the row by its registrable domain. Run `tests/leak_check.py` right after the first seed regeneration, not at the end. Also: the hunt table's "free" claims were only search snippets for half the rows; two of them (a $9/mo package page, an advertise-with-us lead form) were paid when I fetched the add page. Fetch the add path itself before promoting.
