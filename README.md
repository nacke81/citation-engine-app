# Citation Engine (v2 skeleton)

Weekly check of two businesses' listings across the Catalog Directories. Page is behind the shared Supabase sign-in.
Repo holds code and scrubbed fixtures only: no names, addresses, phones, listing data or keys. Real identity lives in
`%LOCALAPPDATA%/citation-engine/identity.json` on the job PC.

- `job/` weekly discovery (Spike s3 methods), owned Chrome only. `weekly.cmd` is the Task Scheduler entry.
- `site/` the page. `db/schema.sql` tables with row-level security.
- `tests/` golden tests 1-4 on scrubbed fixtures, leak check with planted control, page rules.
