-- Directory database (kanban t_b17fd470). GENERATED: edit db/002_directories.sql.tpl and run db/gen_directories_seed.py, never the .sql by hand.
-- Idempotent: safe to apply repeatedly. Re-applying refreshes the Catalog facts but never overwrites live state
-- (agent_access, agent_blocker, last_verified) or any per-business row.
--
-- ce_directories        one row per v1 Catalog Directory (86). Shared reference facts only: no client name, address or phone, ever.
--                       Because it holds no client data it has no owner column: every signed-in user reads it, the job writes with the secret key.
-- ce_directory_status   one row per owner x business x Directory: latest check result, claim_status, queue state, blocker note.
--                       Owner-scoped exactly like ce_runs / ce_checks.
-- ce_directory_biz      view: every Directory x {SCC, NM}, joined to the owner's status row. security_invoker, so RLS on the base tables applies.

create table if not exists public.ce_directories (
  domain              text primary key,
  name                text not null,
  cut                 text,
  priority            int  not null default 4,
  da                  int,
  category            text not null default 'general' check (category in ('general', 'aggregator', 'niche-senior', 'niche-other', 'local')),
  checked_weekly      boolean not null default false,
  weekly_scope        text not null default 'none' check (weekly_scope in ('weekly-25', 'create-discovery-10', 'none')),
  search_method       text,
  search_url_template text,
  zero_marker_known   boolean not null default false,
  zero_marker_text    text,
  claim_markers_verified boolean not null default false,
  claim_markers       text,
  signup_url          text,
  claim_url           text,
  help_url            text,
  cost                text not null default 'unknown' check (cost in ('free', 'paid', 'unknown')),
  cost_note           text,
  account_needed      text not null default 'unknown' check (account_needed in ('yes', 'no', 'unknown')),
  account_note        text,
  verification_methods jsonb not null default '[]'::jsonb,
  build_route         text not null default 'agent' check (build_route in ('agent', 'agency-account', 'aggregator', 'none')),
  build_route_note    text,
  agent_access        text not null default 'unknown' check (agent_access in ('ok', 'blocked', 'unknown')),
  agent_blocker       text,
  agent_blocker_seen_on date,
  agent_blocker_source text check (agent_blocker_source in ('manual', 'weekly', 'transition')),
  notes               text,
  last_verified       date,
  updated_at          timestamptz not null default now()
);

-- a table built from an older draft of this migration gets the column too
alter table public.ce_directories add column if not exists agent_blocker_source text check (agent_blocker_source in ('manual', 'weekly', 'transition'));

create table if not exists public.ce_directory_status (
  id               uuid primary key default gen_random_uuid(),
  owner            uuid not null default auth.uid() references auth.users(id) on delete cascade,
  biz              text not null check (biz in ('SCC', 'NM')),
  directory        text not null references public.ce_directories(domain) on update cascade,
  last_result      text check (last_result in ('found', 'absent', 'couldnt_check', 'unsearchable')),
  last_checked_on  date,
  last_url         text,
  last_match       boolean,
  last_note        text,
  claim_status     text check (claim_status in ('claimed', 'unclaimed', 'unknown')),
  claim_evidence_text text,
  queue_state      text check (queue_state in ('queued', 'submitted', 'pending-verify', 'needs-human', 'live', 'rejected')),
  queue_row_id     text,
  queue_kind       text check (queue_kind in ('fix', 'create')),
  queue_note       text,
  queue_state_at   date,
  updated_at       timestamptz not null default now(),
  unique (owner, biz, directory)
);

do $$
declare t text;
begin
  foreach t in array array['ce_directories', 'ce_directory_status'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from anon', t);
    -- the page only reads; the job writes with the secret key
    execute format('revoke all on public.%I from authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
  end loop;
end $$;

drop policy if exists "all signed-in: read" on public.ce_directories;
create policy "all signed-in: read" on public.ce_directories for select to authenticated using (true);
drop policy if exists "own rows: read" on public.ce_directory_status;
create policy "own rows: read" on public.ce_directory_status for select to authenticated using (owner = auth.uid());

create index if not exists ce_directory_status_dir on public.ce_directory_status(directory);

create or replace view public.ce_directory_biz with (security_invoker = true) as
select d.domain, b.biz,
       s.last_result, s.last_checked_on, s.last_url, s.last_match, s.last_note,
       s.claim_status, s.claim_evidence_text,
       s.queue_state, s.queue_row_id, s.queue_kind, s.queue_note, s.queue_state_at,
       s.updated_at as status_updated_at
from public.ce_directories d
cross join (values ('SCC'), ('NM')) as b(biz)
left join public.ce_directory_status s on s.directory = d.domain and s.biz = b.biz;
revoke all on public.ce_directory_biz from anon;
revoke all on public.ce_directory_biz from authenticated;
grant select on public.ce_directory_biz to authenticated;

-- Seed: the 86 Catalog rows. Static facts refresh on conflict; live state (agent_access, agent_blocker, agent_blocker_seen_on, last_verified) is kept.
insert into public.ce_directories (domain, name, cut, priority, da, category, checked_weekly, weekly_scope, search_method, search_url_template,
  zero_marker_known, zero_marker_text, claim_markers_verified, claim_markers, signup_url, claim_url, help_url, cost, cost_note, account_needed,
  account_note, verification_methods, build_route, build_route_note, agent_access, agent_blocker, agent_blocker_seen_on, agent_blocker_source, notes, last_verified)
select s.domain, s.name, s.cut, s.priority, s.da, s.category, s.checked_weekly, s.weekly_scope, s.search_method, s.search_url_template,
  s.zero_marker_known, s.zero_marker_text, s.claim_markers_verified, s.claim_markers, s.signup_url, s.claim_url, s.help_url, s.cost, s.cost_note,
  s.account_needed, s.account_note, coalesce(s.verification_methods, '[]'::jsonb), s.build_route, s.build_route_note, s.agent_access, s.agent_blocker,
  s.agent_blocker_seen_on, s.agent_blocker_source, s.notes, s.last_verified
from jsonb_to_recordset($seed$@@SEED_JSON@@$seed$::jsonb) as s(
  domain text, name text, cut text, priority int, da int, category text, checked_weekly boolean, weekly_scope text, search_method text,
  search_url_template text, zero_marker_known boolean, zero_marker_text text, claim_markers_verified boolean, claim_markers text, signup_url text,
  claim_url text, help_url text, cost text, cost_note text, account_needed text, account_note text, verification_methods jsonb, build_route text,
  build_route_note text, agent_access text, agent_blocker text, agent_blocker_seen_on date, agent_blocker_source text, notes text, last_verified date)
on conflict (domain) do update set
  name = excluded.name, cut = excluded.cut, priority = excluded.priority, da = excluded.da, category = excluded.category,
  checked_weekly = excluded.checked_weekly, weekly_scope = excluded.weekly_scope, search_method = excluded.search_method,
  search_url_template = excluded.search_url_template, zero_marker_known = excluded.zero_marker_known, zero_marker_text = excluded.zero_marker_text,
  claim_markers_verified = excluded.claim_markers_verified, claim_markers = excluded.claim_markers, signup_url = excluded.signup_url,
  claim_url = excluded.claim_url, help_url = excluded.help_url, cost = excluded.cost, cost_note = excluded.cost_note,
  account_needed = excluded.account_needed, account_note = excluded.account_note, verification_methods = excluded.verification_methods,
  build_route = excluded.build_route, build_route_note = excluded.build_route_note, notes = excluded.notes, updated_at = now();
