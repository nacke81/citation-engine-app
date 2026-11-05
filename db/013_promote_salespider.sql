-- Promote salespider.com to buildable for SCC (kanban t_41f55574; Nate ruling on evidence t_1061017b: free claim page, Name + City form, no price).
-- Data only and idempotent: three columns (build_eligible, build_route, build_route_note) on exactly this 1 row. No insert, no delete, no other column.
-- Numbered 013 because 011 and 012 were taken by reason_code and weekly_metrics.
-- The seed generator (db/gen_directories_seed.py PROMOTED_013) carries the same row so a reseed keeps it.
update public.ce_directories
   set build_eligible = true,
       build_route = 'agent',
       build_route_note = 'Promoted t_1061017b: free claim page; agent builds, parks before any code or CAPTCHA step it cannot do free.'
 where domain in ('salespider.com');
