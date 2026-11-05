-- Citation Engine tables in the People CRM Supabase project (same sign-in as Broker Watch; no extra cost).
-- Every row is owned by one login; row-level security is the privacy story. The weekly job writes with the secret key from this PC
-- and stamps owner explicitly; the page never sends owner and only reads.

create table if not exists public.ce_runs (
  id               uuid primary key default gen_random_uuid(),
  owner            uuid not null default auth.uid() references auth.users(id) on delete cascade,
  started_at       timestamptz not null default now(),
  finished_at      timestamptz,
  status           text not null default 'running' check (status in ('running', 'ok', 'failed')),
  chrome_before    int,
  chrome_during    int,
  chrome_after     int,
  chrome_equal     boolean,
  owned_alive_after int[] not null default '{}',
  guards           jsonb,
  counts           jsonb,
  score            jsonb,
  error            text
);

create table if not exists public.ce_checks (
  id          uuid primary key default gen_random_uuid(),
  owner       uuid not null default auth.uid() references auth.users(id) on delete cascade,
  run_id      uuid not null references public.ce_runs(id) on delete cascade,
  biz         text not null check (biz in ('SCC', 'NM')),
  directory   text not null,
  checked_on  date not null,
  result      text not null check (result in ('found', 'absent', 'couldnt_check', 'unsearchable')),
  url         text,
  nap_shown   text,
  name_match  boolean,
  street_match boolean,
  phone_match boolean,
  match       boolean,
  method      text,
  note        text,
  unique (run_id, biz, directory)
);

do $$
declare t text;
begin
  foreach t in array array['ce_runs', 'ce_checks'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('alter table public.%I force row level security', t);
    execute format('revoke all on public.%I from anon', t);
    -- the page only reads; the job writes with the secret key
    execute format('revoke all on public.%I from authenticated', t);
    execute format('grant select on public.%I to authenticated', t);
    execute format('drop policy if exists "own rows: read" on public.%I', t);
    execute format('create policy "own rows: read" on public.%I for select to authenticated using (owner = auth.uid())', t);
  end loop;
end $$;

create index if not exists ce_checks_run on public.ce_checks(run_id);
create index if not exists ce_runs_owner on public.ce_runs(owner, started_at);

-- Slice 1 (fix list): per found listing, the NAP fields that differ from canonical: [{field, live, canonical}]. Null = none recorded.
alter table public.ce_checks add column if not exists diffs jsonb;

-- t_93ae9b6b: why a row needs a person (code from site/reasons.js REASONS). Nullable; see db/011_reason_code.sql.
alter table public.ce_directory_status add column if not exists reason_code text;
-- Weekly progress chart snapshots (kanban t_43e88fb7). Additive, idempotent. Apply BEFORE the app merge (repo lesson 10/20).
-- One row per business per weekly run. metrics = the 12 home tile numbers (null = a past week that could not be rebuilt honestly: a gap, never a zero).
-- sources = where each number came from: ce_checks | queue history | gap | snapshot. The weekly job writes with the secret key; the page only reads.
create table if not exists public.ce_weekly_metrics (
  id          uuid primary key default gen_random_uuid(),
  owner       uuid not null default auth.uid() references auth.users(id) on delete cascade,
  biz         text not null check (biz in ('SCC', 'NM')),
  run_id      uuid not null references public.ce_runs(id) on delete cascade,
  week_index  int  not null check (week_index >= 0),
  captured_on date not null,
  metrics     jsonb not null,
  sources     jsonb,
  created_at  timestamptz not null default now(),
  unique (owner, biz, run_id),
  unique (owner, biz, week_index)
);
alter table public.ce_weekly_metrics enable row level security;
alter table public.ce_weekly_metrics force row level security;
revoke all on public.ce_weekly_metrics from anon;
revoke all on public.ce_weekly_metrics from authenticated;
grant select on public.ce_weekly_metrics to authenticated;
drop policy if exists "own rows: read" on public.ce_weekly_metrics;
create policy "own rows: read" on public.ce_weekly_metrics for select to authenticated using (owner = auth.uid());
create index if not exists ce_weekly_metrics_biz on public.ce_weekly_metrics(owner, biz, week_index);
