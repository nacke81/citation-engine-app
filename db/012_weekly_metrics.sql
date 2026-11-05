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
