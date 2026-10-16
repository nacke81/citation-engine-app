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
