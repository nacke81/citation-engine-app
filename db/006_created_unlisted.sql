-- created-unlisted queue state (kanban t_f707b644): the listing exists on the Directory but is not public yet, or is public without full NAP. ADDITIVE: only widens a check constraint.
-- Apply BEFORE merging/running the app change that writes it (portal PR #54 lesson). Idempotent. The portal snapshot maps this state to `submitted`, so no portal change is needed.
alter table public.ce_directory_status drop constraint if exists ce_directory_status_queue_state_check;
alter table public.ce_directory_status add constraint ce_directory_status_queue_state_check
  check (queue_state in ('queued', 'found', 'claimed-unverified', 'created-unlisted', 'submitted', 'pending-verify', 'needs-human', 'live', 'rejected'));
