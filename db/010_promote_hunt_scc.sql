-- Promote 8 hunt Directories to buildable for SCC (kanban t_9675083c; approved in t_ff170c85).
-- Data only and idempotent: three columns (build_eligible, build_route, build_route_note) on exactly these 8 rows. No insert, no delete, no other column.
-- Safe to apply before or after the app merge: main's buildrows already honors build_eligible.
-- The seed generator (db/gen_directories_seed.py PROMOTED_SCC) carries the same list so a reseed keeps it.
update public.ce_directories
   set build_eligible = true,
       build_route = 'agent',
       build_route_note = 'Promoted t_ff170c85: free self-serve signup; agent builds, parks before any code or CAPTCHA step it cannot do free.'
 where domain in ('yellowpagecity.com', 'bizhwy.com', 'expressbusinessdirectory.com', 'smartcustomer.com',
                  'usbizs.com', 'usaypage.com', 'trustpilot.com', 'threebestrated.com');
