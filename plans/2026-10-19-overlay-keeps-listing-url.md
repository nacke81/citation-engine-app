# Plan 2026-10-19: queue overlay keeps the resolved listing URL (kanban t_693dfc92, follow-up)

Latest lesson read: docs/lessons/2026-09-21-nm-canonical-street-is-an-engine-input.md (v1 repo; this repo has no docs/lessons). Applied: the engine owns the data it writes, so the overlay must not destroy engine-resolved facts. Prior plan: plans/2026-10-19-directory-listings-truth.md. Nate ruling 2026-10-19: open a follow-up PR.

## Defect
job/buildqueue.py overlay_directories sets d["url"] = None whenever queue state is not "live". The 4 queued SCC rows (yellowpages, superpages, dexknows, mapquest) lose their /mip/ /bpp/ /bp/ permalink in prod while urlKind stays "listing".

## Fix
Clear url only when the row is not a resolved listing (urlKind != "listing"). Queued rows with urlKind "listing" keep url and urlKind. Create rows keep url None.

## Test
tests/queue_test.py: the queued domains with listing URLs keep url + urlKind "listing" after overlay while state is needs-human; a search row stays null.
