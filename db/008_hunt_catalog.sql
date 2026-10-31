-- Hunt catalog schema (kanban t_ab039aed). STATIC, no rows. ADDITIVE and idempotent.
-- DEPLOY ORDER: (1) apply this 008, safe for main (main ignores the new columns); (2) merge + make sure the weekly PC has pulled; (3) apply 009_hunt_catalog_seed.sql.
-- Never apply 009 before the merge is pulled: main's buildrows would queue the hunt rows.
-- 1. build_eligible: the weekly buildrows step skips a Directory whose build_eligible is false, so a catalog-only row never gets an SCC queue row.
--    Existing rows default to true (behavior unchanged).
-- 2. vertical / weekly_checkable / source: the 2026-10-30 Catalog bar split (Intelligence/decisions/2026-10-30-citation-catalog-bar-split.md).
--    NULLABLE, no default: unknown stays unknown, nothing is backfilled on the 86 older rows.
-- 3. category CHECK widened (not squashed) with the hunt verticals.
alter table public.ce_directories add column if not exists build_eligible boolean not null default true;
alter table public.ce_directories add column if not exists vertical text;
alter table public.ce_directories add column if not exists weekly_checkable text;
alter table public.ce_directories add column if not exists source text;

alter table public.ce_directories drop constraint if exists ce_directories_category_check;
alter table public.ce_directories add constraint ce_directories_category_check
  check (category in ('general', 'aggregator', 'niche-senior', 'niche-other', 'local', 'health-senior-care', 'home-services', 'legal', 'local-regional', 'restaurant'));
