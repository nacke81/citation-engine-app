# Lesson: a tenant guard is config plus a lock, not `if client != "SCC": refuse` (t_cb7bad04)

`record_transition` refused every client but SCC with one `if`. That single line also switched off every part of the park that is NOT SCC-specific (Your turn verification row, Verify Now allowlist, Directory DB), and NM work fell back to a writer that only touched the queue file. Mike's Verify Now runs on NM were blocked until a card found it.

Rule: when a path is "SCC only", list which steps are truly tenant-specific (queue file, portal client id, row-id prefix, snapshot, client Activities) and move those into one per-tenant config. Everything else stays shared. Then add a lock that checks the tenant, the row id and the queue file BEFORE any read or write, so widening the path cannot let one tenant's park write the other's row.

Test it both ways (NM park on an SCC row, SCC park on an `nm-` row), assert the portal call carries only the tenant's own client id, and add a mutation that removes the lock and shows the cross-tenant write then HAPPENS. A refusal test that never saw the unsafe path succeed proves nothing.
