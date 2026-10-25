-- Catalog flags (kanban t_e0abca7d). ADDITIVE and NULLABLE: nothing dropped, nothing backfilled, no NOT NULL without a default.
-- Apply BEFORE merging the app change that reads/writes them (portal PR #54 lesson). Idempotent.
-- 1. cost period: ce_directories.cost stays free|paid|unknown; amount + period get their own columns (period: one-time, /mo, /yr).
alter table public.ce_directories add column if not exists cost_amount numeric;
alter table public.ce_directories add column if not exists cost_period text check (cost_period in ('one-time', '/mo', '/yr'));
-- 2. dead Catalog rows (dead domain, parked, DNS gone, search 404). The row is kept; the build skips it.
alter table public.ce_directories add column if not exists dead boolean not null default false;
alter table public.ce_directories add column if not exists dead_reason text;
alter table public.ce_directories add column if not exists dead_on date;
-- 3. the queue gains the internal state `found` (SCC already listed, claim not done).
alter table public.ce_directory_status drop constraint if exists ce_directory_status_queue_state_check;
alter table public.ce_directory_status add constraint ce_directory_status_queue_state_check
  check (queue_state in ('queued', 'found', 'submitted', 'pending-verify', 'needs-human', 'live', 'rejected'));
