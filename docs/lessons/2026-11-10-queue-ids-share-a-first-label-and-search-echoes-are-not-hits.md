# Lesson: queue ids use the first domain label, and a search page that echoes your query is not a hit (t_24ffb698)

Cite: `plans/2026-11-10-scc-bl14-promote-016.md`.

Two traps while promoting the 14 ex-BrightLocal sites.

1. `buildrows.row_id` is `kind-<first label>`. yellowpages.net and yellowpages.com both want `create-yellowpages`, and the old code raised `would collide` for the whole run, so one new row could have stopped every other SCC row from queueing. Found only because the new B12 test runs the real builder over the full seed on an empty queue. Fix: on a collision use the full domain (`create-yellowpages-net`) and re-stamp the approval row_id; a second collision still raises.
Rule: before adding any Directory, check its first label against the existing ids; run the real builder on the whole seed, not on the new rows alone.

2. Directory search pages print your query in the title, the breadcrumb and a "results for" heading. A grep for the client name or phone matches that echo on every site. Count a hit only when the match sits in a result row with the client's street or city. Where a site cannot be searched (Cloudflare interstitial, 403, down) write "not checkable", never "not listed".
Also: a full-page Cloudflare "Just a moment" page is a wall, not a CAPTCHA widget, so it is a skip even when the same domain also loads Turnstile on a form.
