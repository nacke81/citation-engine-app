# 2026-10-30: a Directory nobody searched is not absent

- The weekly finder read a hand-kept list (`cfg.DIRS`, 25). 61 of 86 `ce_directories` rows were never checked, so the portal under-reported. The list now comes from `ce_directories` at run start (`job/dirlist.py`); the seed JSON is only the loud offline fallback.
- Widening the list is safe only because `judge.combine` already needs a same-method positive control for `absent`. A Directory with no discovery row falls to `couldnt_check`, and the job labels it `no-method` so the portal says "not checked", not "absent".
- Do not add a search method from a guess. The 61 stay `no-method` until someone looks at the real site and proves the method on a known listing; that is separate per-Directory work.
- A `no-method` row must not be written to `ce_directory_status`: it would overwrite an earlier real verdict (create-discovery, hand check) with `couldnt_check`.
- Runtime does not grow with the list when the extra rows have no method: the 25-Directory dry run took 52 minutes (3116 s). Every method added later costs roughly 2 minutes per Directory per business, so re-measure before enabling any.
- A dry run can exit 1 on `window_count.equal` when the machine's other Chrome windows change during a 50-minute run; read `owned_alive_after` and the guards before blaming the change.
