-- One place for every Directory's click-by-click steps (kanban t_413687a7; Nate 2026-11-13, Mike ask). The app shows these rows; the agents run from them. No copies.
-- Steps carry PLACEHOLDERS only ({business_name} {login_email} {phone} {website} {vault_item}), never tenant values, codes or secrets (job/playbook.py validates before any write).
-- Idempotent DDL, no data. REQUIRES 002 (ce_directories). Apply only after review and merge; writes go through job/playbook.py with the service key.
create table if not exists public.ce_directory_playbooks (
  id              uuid primary key default gen_random_uuid(),
  domain          text not null references public.ce_directories(domain) on delete cascade,
  task            text not null check (task in ('check', 'create', 'claim', 'fix', 'verify')),
  steps           jsonb not null check (jsonb_typeof(steps) = 'array' and jsonb_array_length(steps) > 0),
  send_is_signup  boolean not null default false check (not send_is_signup or task = 'verify'),
  source          text,
  last_proven_at  timestamptz,
  updated_at      timestamptz not null default now(),
  version         int not null default 1,
  unique (domain, task)
);

alter table public.ce_directory_playbooks enable row level security;
grant select on public.ce_directory_playbooks to authenticated;
drop policy if exists "all signed-in: read" on public.ce_directory_playbooks;
create policy "all signed-in: read" on public.ce_directory_playbooks for select to authenticated using (true);
