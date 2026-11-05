# Lesson: a default argument is an unguarded reader (t_f5d80477)

`proof.recheck_verdict` looked guarded-ready: it called `recheck.read_listing(url, None, own_chrome, canonical)`. But `plain=None` means `get_page` falls back to `plain_fetch`, a real GET to the Directory. Wrapping only the Chrome reader would have left the first read of every Proof row outside the SiteGuard, and the cap would still have been blowable.

Rule: when routing reads through a guard, grep each reader entry point for `x or real_fetch` / `=None` fallbacks and wrap every route, not the one you can see. Then count requests per domain with recording readers (plain AND chrome), not the guard's own ledger: the ledger is one read per URL (`same_read`), requests are what the site sees.
