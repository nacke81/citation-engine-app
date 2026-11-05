# Lesson: count the requests, not the code paths (t_e34fc55c r3)

Round 2 passed its own tests and still read one known URL three times per transport: the plan helper handed the same URL to search, pattern and phone, and only `found` settled a pair. Two more repeats hid in data: a found search page equals the plan's search URL, and `pattern_urls` lists the NM MapQuest URL twice.

Rule: for any "read once" claim, run the real entry point (`discover_all`, `ladder`) with a recording fetcher and assert `len(urls) == len(set(urls))` per transport. Run the same count offline against the real queue and the last run before asking for review. A guard that counts reads cannot see a loop above it.
