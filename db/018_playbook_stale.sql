-- A playbook row that came from an old vault note, or that a later run contradicted, is kept but flagged (kanban t_2cb780c2).
-- The app shows a "Stale" chip; a run that reaches its goal clears it (job/playbook.py set with last_proven_at). Idempotent DDL, no data. REQUIRES 017.
alter table public.ce_directory_playbooks add column if not exists stale boolean not null default false;
