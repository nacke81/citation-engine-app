-- Reason badge code (kanban t_93ae9b6b). Additive, nullable, idempotent. Apply BEFORE the app merge (repo lesson 10/20).
-- The worker that parks a row writes the code; the page reads it through ce_directory_biz (the view the app selects from).
-- The one-time backfill is db/011_reason_code_backfill.sql. Run it after this file.
alter table public.ce_directory_status add column if not exists reason_code text;

-- Same view as 003 with reason_code appended last (create or replace view only allows new columns at the end).
create or replace view public.ce_directory_biz with (security_invoker = true) as
select d.domain, b.biz,
       s.last_result, s.last_checked_on, s.last_url, s.last_match, s.last_note,
       s.claim_status, s.claim_evidence_text,
       s.queue_state, s.queue_row_id, s.queue_kind, s.queue_note, s.queue_state_at,
       s.updated_at as status_updated_at,
       s.build_action, s.proof_url, s.proof_nap, s.proof_at, s.proof_nap_match,
       s.reason_code
from public.ce_directories d
cross join (values ('SCC'), ('NM')) as b(biz)
left join public.ce_directory_status s on s.directory = d.domain and s.biz = b.biz;
revoke all on public.ce_directory_biz from anon;
revoke all on public.ce_directory_biz from authenticated;
grant select on public.ce_directory_biz to authenticated;
