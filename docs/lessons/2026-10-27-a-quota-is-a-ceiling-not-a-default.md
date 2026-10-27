# Lesson 2026-10-27: a free-plan quota is a ceiling in code, not a default in a config

Card t_295208a6 (Moz Domain Authority). The card said "cap rows per run, default 50". Mike's ruling arrived mid-build: free plan only, 50 rows per calendar month across all runs, yearly refresh.

- A per-run cap is not a monthly cap. The weekly run would have spent 50 rows every week. The ceiling has to be counted from stored state (`da_checked_on` in this month) and from the provider's own count (`quota.lookup`), and the smaller allowance wins. The env knob (`MOZ_MAX_ROWS`) may only lower it.
- Fail closed on the quota check. If the quota lookup fails, nothing is fetched. Over-spending a free plan is worse than waiting a week.
- Stamp the check date even when the provider returns no score, or one unscorable domain is retried forever and eats the next month's rows.
- Keep the source with the number (`da_source`). A worksheet number and a Moz number look the same in an int column; the snapshot rule (`snapshot.apply_authority`) shows only `moz` and nulls the rest, in one function every write path passes through. A DB trigger keeps the seed re-upsert from overwriting a Moz value.
- Test the boundaries, not the middle: 364 vs 365 days, 45 of 50 used, 50 of 50 used, MOZ_MAX_ROWS=500, quota lookup down, next calendar month.
- Runner rules: heredocs are not allowed; edit files with the patch tool or a script file.
