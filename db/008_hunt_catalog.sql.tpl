-- Hunt catalog rows (kanban t_ab039aed). GENERATED: edit db/008_hunt_catalog.sql.tpl and run python db/gen_directories_seed.py --hunt, never the .sql by hand.
-- ADDITIVE and idempotent. Apply BEFORE merging/running the app change that reads build_eligible (portal PR #54 lesson).
-- 1. build_eligible: the weekly buildrows step skips a Directory whose build_eligible is false, so a catalog-only row never gets an SCC queue row.
--    Existing rows default to true (behavior unchanged). Every hunt row below is inserted false.
-- 2. vertical / weekly_checkable / source: the 2026-10-30 Catalog bar split (Intelligence/decisions/2026-10-30-citation-catalog-bar-split.md).
--    NULLABLE, no default: unknown stays unknown, nothing is backfilled on the 86 older rows.
-- 3. category CHECK widened (not squashed) with the hunt verticals.
-- Seed: the hunt rows (cycle 1 + cycle 2). ON CONFLICT DO NOTHING: a re-apply never touches a row that already exists, so live state and
-- any later build_eligible change are kept.
alter table public.ce_directories add column if not exists build_eligible boolean not null default true;
alter table public.ce_directories add column if not exists vertical text;
alter table public.ce_directories add column if not exists weekly_checkable text;
alter table public.ce_directories add column if not exists source text;

alter table public.ce_directories drop constraint if exists ce_directories_category_check;
alter table public.ce_directories add constraint ce_directories_category_check
  check (category in ('general', 'aggregator', 'niche-senior', 'niche-other', 'local', 'health-senior-care', 'home-services', 'legal', 'local-regional', 'restaurant'));

insert into public.ce_directories (domain, name, cut, priority, da, category, checked_weekly, weekly_scope, search_method, search_url_template,
  zero_marker_known, zero_marker_text, claim_markers_verified, claim_markers, signup_url, claim_url, help_url, cost, cost_note, account_needed,
  account_note, verification_methods, build_route, build_route_note, agent_access, agent_blocker, agent_blocker_seen_on, agent_blocker_source, notes,
  last_verified, vertical, weekly_checkable, source, build_eligible)
select s.domain, s.name, s.cut, s.priority, s.da, s.category, s.checked_weekly, s.weekly_scope, s.search_method, s.search_url_template,
  s.zero_marker_known, s.zero_marker_text, s.claim_markers_verified, s.claim_markers, s.signup_url, s.claim_url, s.help_url, s.cost, s.cost_note,
  s.account_needed, s.account_note, coalesce(s.verification_methods, '[]'::jsonb), s.build_route, s.build_route_note, s.agent_access, s.agent_blocker,
  s.agent_blocker_seen_on, s.agent_blocker_source, s.notes, s.last_verified, s.vertical, s.weekly_checkable, s.source, s.build_eligible
from jsonb_to_recordset($seed$@@SEED_JSON@@$seed$::jsonb) as s(
  domain text, name text, cut text, priority int, da int, category text, checked_weekly boolean, weekly_scope text, search_method text,
  search_url_template text, zero_marker_known boolean, zero_marker_text text, claim_markers_verified boolean, claim_markers text, signup_url text,
  claim_url text, help_url text, cost text, cost_note text, account_needed text, account_note text, verification_methods jsonb, build_route text,
  build_route_note text, agent_access text, agent_blocker text, agent_blocker_seen_on date, agent_blocker_source text, notes text, last_verified date,
  vertical text, weekly_checkable text, source text, build_eligible boolean)
on conflict (domain) do nothing;
