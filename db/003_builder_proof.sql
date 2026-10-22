-- Builder Proof columns (kanban t_eef79f15). ADDITIVE and NULLABLE: no default, no backfill, no NOT NULL, nothing dropped.
-- Apply BEFORE merging the app change that reads them (portal PR #54 lesson). Idempotent.
-- A row counts as a result (New listings live / Claimed / Fixed) only when queue_state = 'live' AND all four proof fields are set
-- and proof_nap_match is true. build_action says which result: new | claim | fix. Nothing here stores a total.
alter table public.ce_directory_status add column if not exists build_action text check (build_action in ('new', 'claim', 'fix'));
alter table public.ce_directory_status add column if not exists proof_url text;
alter table public.ce_directory_status add column if not exists proof_nap text;
alter table public.ce_directory_status add column if not exists proof_at timestamptz;
alter table public.ce_directory_status add column if not exists proof_nap_match boolean;

create or replace view public.ce_directory_biz with (security_invoker = true) as
select d.domain, b.biz,
       s.last_result, s.last_checked_on, s.last_url, s.last_match, s.last_note,
       s.claim_status, s.claim_evidence_text,
       s.queue_state, s.queue_row_id, s.queue_kind, s.queue_note, s.queue_state_at,
       s.updated_at as status_updated_at,
       s.build_action, s.proof_url, s.proof_nap, s.proof_at, s.proof_nap_match
from public.ce_directories d
cross join (values ('SCC'), ('NM')) as b(biz)
left join public.ce_directory_status s on s.directory = d.domain and s.biz = b.biz;
revoke all on public.ce_directory_biz from anon;
revoke all on public.ce_directory_biz from authenticated;
grant select on public.ce_directory_biz to authenticated;
