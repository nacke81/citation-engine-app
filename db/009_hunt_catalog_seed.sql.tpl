-- Hunt catalog rows (kanban t_ab039aed). GENERATED: edit db/009_hunt_catalog_seed.sql.tpl and run python db/gen_directories_seed.py --hunt, never the .sql by hand.
-- Rows only, no DDL. REQUIRES 008_hunt_catalog.sql applied first. APPLY ONLY AFTER the app change is merged and the weekly PC has pulled it:
-- main's buildrows does not know build_eligible and would queue these rows.
-- Every row is inserted build_eligible=false (catalog-only). ON CONFLICT DO NOTHING: a re-apply never touches an existing row.
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
