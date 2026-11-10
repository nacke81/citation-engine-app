-- Exclude the lead-gen/referral class and agency lead magnets from building (kanban t_e20d28d9; Nate ruling 2026-11-09). GENERATED: python db/gen_directories_seed.py --hunt.
-- Data only and idempotent: UPDATE of three columns (build_eligible, build_route, build_route_note) on exactly the excluded domains. No insert, no delete, no DDL, no other column.
-- caring.com is the live row it changes (build_eligible was true, route agent). A domain absent from ce_directories is simply not matched.
update public.ce_directories
   set build_eligible = false,
       build_route = 'none',
       build_route_note = 'declined: paid lead form (Mike 10/26); lead-gen/referral class, never promote'
 where domain in ('agingcare.com', 'aplaceformom.com', 'caring.com', 'payingforseniorcare.com', 'senioradvisor.com', 'seniorly.com');
update public.ce_directories
   set build_eligible = false,
       build_route = 'none',
       build_route_note = 'excluded: agency lead magnet (get-listed page hands contact details to a competing agency); never promote'
 where domain in ('whosinmycity.com');
