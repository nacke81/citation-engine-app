-- Moz Domain Authority per Directory (kanban t_295208a6). ADDITIVE and idempotent. Apply BEFORE merging/running the app change that writes it.
-- da_source: where ce_directories.da came from. 'moz' = Moz Links API (the only value the portal shows as authority); 'worksheet' = the 2026-10-06 hand sheet (never shown as Moz).
-- da_checked_on: day Moz was last asked about this Directory (set even when Moz returned no score, so the yearly queue cannot stall on one domain).
alter table public.ce_directories add column if not exists da_source text check (da_source in ('moz', 'worksheet'));
alter table public.ce_directories add column if not exists da_checked_on date;

-- The 27 existing numbers are the worksheet's. Only rows that have no source yet.
update public.ce_directories set da_source = 'worksheet' where da is not null and da_source is null;

-- A Moz value is never overwritten by a worksheet value: the 002 seed re-upsert writes `da = excluded.da` on conflict, so keep the Moz number
-- whenever a write changes da without a fresh Moz check (da_checked_on unchanged). The Moz refresh always moves da_checked_on, so it passes.
create or replace function public.ce_directories_keep_moz_da() returns trigger language plpgsql as $$
begin
  if old.da_source = 'moz' and new.da is distinct from old.da and new.da_checked_on is not distinct from old.da_checked_on then
    new.da := old.da; new.da_source := old.da_source;
  end if;
  return new;
end $$;
drop trigger if exists ce_directories_keep_moz_da on public.ce_directories;
create trigger ce_directories_keep_moz_da before update on public.ce_directories for each row execute function public.ce_directories_keep_moz_da();
