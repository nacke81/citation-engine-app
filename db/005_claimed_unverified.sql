-- claimed-unverified queue state (kanban t_d13bd638): SCC found + claimed, edits ID-gated (dnb). ADDITIVE: only widens a check constraint.
-- Apply BEFORE merging the app change that writes it (portal PR #54 lesson). Idempotent.
alter table public.ce_directory_status drop constraint if exists ce_directory_status_queue_state_check;
alter table public.ce_directory_status add constraint ce_directory_status_queue_state_check
  check (queue_state in ('queued', 'found', 'claimed-unverified', 'submitted', 'pending-verify', 'needs-human', 'live', 'rejected'));
