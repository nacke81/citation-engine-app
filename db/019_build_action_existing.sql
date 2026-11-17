-- build_action `existing` (kanban t_dc4ffd67): a listing NM did not build, found by the scan, NAP verified by a read.
-- WIDENING ONLY: the allowed set goes from ('new','claim','fix') to ('new','claim','fix','existing'). No column, no row, no view is touched
-- (ce_directory_biz selects the column, not the constraint, so it needs no recreate). Idempotent. Apply BEFORE merging the app change (repo lesson).
-- Readback: select pg_get_constraintdef(oid) from pg_constraint where conrelid = 'public.ce_directory_status'::regclass and contype = 'c' and pg_get_constraintdef(oid) like '%build_action%';
begin;
do $$
declare c text;
begin
  for c in select conname from pg_constraint
           where conrelid = 'public.ce_directory_status'::regclass and contype = 'c' and pg_get_constraintdef(oid) like '%build_action%'
  loop
    execute format('alter table public.ce_directory_status drop constraint %I', c);
  end loop;
end $$;
alter table public.ce_directory_status add constraint ce_directory_status_build_action_check
  check (build_action in ('new', 'claim', 'fix', 'existing'));
commit;
