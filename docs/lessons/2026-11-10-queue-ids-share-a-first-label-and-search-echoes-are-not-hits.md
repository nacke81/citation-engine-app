# Lesson: queue ids use the first domain label, and a search page that echoes your query is not a hit (t_24ffb698)

Cite: `plans/2026-11-10-scc-bl14-promote-016.md`.

Two traps while promoting the 14 ex-BrightLocal sites.

1. `buildrows.row_id` is `kind-<first label>`. yellowpages.net and yellowpages.com both want `create-yellowpages`, and the old code raised `would collide` for the whole run, so one new row could have stopped every other SCC row from queueing. Found only because the new B12 test runs the real builder over the full seed on an empty queue. A collision fallback alone is NOT enough: prod has `fix-yellowpages` (.com) and no `create-yellowpages`, so the fallback never fires there and the .net row would be named `create-yellowpages`. Fix: when another Catalog domain shares the first label, the id uses the full domain up front (`create-yellowpages-net`) and the approval row_id is re-stamped (tested on the live-queue shape); the collision fallback stays as a backstop. Two more places compared by brand and are fixed too: `build_runner.same_directory` (two separate Catalog domains are never the same Directory, so the .com claim playbook cannot pass the `--row` guard for the .net row; acompio/tupalo aliases still hold) and `mail_scan.mail_is_from` (a From on another same-brand domain is not this Directory). All mutation checked.
Rule: a first label or brand is never an identity. Before adding a Directory, search the Catalog for the same label on another TLD and check every place that compares by label (row ids, the `--row` guard, mail match); run the real builder over the live-queue shape, not on the new rows alone.

2. Directory search pages print your query in the title, the breadcrumb and a "results for" heading. A grep for the client name or phone matches that echo on every site. Count a hit only when the match sits in a result row with the client's street or city. Where a site cannot be searched (Cloudflare interstitial, 403, down) write "not checkable", never "not listed".
Also: a full-page Cloudflare "Just a moment" page is a wall, not a CAPTCHA widget, so it is a skip even when the same domain also loads Turnstile on a form.

## Addendum (review round 2): tighten matching against the alias pairs, and fail closed
- A rule that rejects "another host with the same brand" also rejects alias TLDs (tupalo.co for tupalo.com, acompio.com for acompio.us). Reject only a host that is a DIFFERENT Catalog domain, the same rule `same_directory` uses. Check every tightened match against the alias pairs.
- `catalog_domains.domains()` returns None (not an empty set, not cached) when the Catalog file is unreadable. `same_directory` then treats two different domains as different, and `mail_is_from` rejects a same-brand From on another host. It never falls back to brand matching. The read is a local file and does not depend on CE_DIRECTORIES_WRITE.
