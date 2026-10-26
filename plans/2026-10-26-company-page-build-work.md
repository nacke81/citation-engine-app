# Plan 2026-10-26: build work on the company page, client-agnostic Directories tab (kanban t_eafb85da)

Latest lesson read: none exist in this repo (no docs/lessons). Prior plan: plans/2026-10-25-buildrows.md and 2026-10-26-batch9-fixes.md. Applied: stdlib/no-dependency pure functions, tests import the real markup, no job/ edits, no queue write.

Rule (Mike): client data lives on the company page; the Directories tab shows only Directory facts.

1. `builder.js`: `builderRows()` rows gain display fields (name, queue chip key + label, note/gate, link, last-change date, `proofPending`). State logic is unchanged, so page totals and home cards share one code path. Directory-level block reason (formerly `bizStatus`) moves here. `QUEUE_LABEL` moves here.
2. `render.js`: `bizHtml(runs, checks, b, dbs)` renders In flight (To build split new/claim/fix, Waiting, Needs a person), Results (New live, Claimed, Fixed), then the finder groups. Group ids `grp-<name>`; rows carry `data-dir`. Live without Proof shows "Live, proof pending". Home card: header links `#SCC`, every stat links `#SCC/<group>` (no nested anchors).
3. `app.js`: hash `#SCC/<group>` or `#SCC/<domain>` scrolls to the group/row.
4. `directories.js`: remove `bizStatus`, `bzs` chips, `bizBlocks`; add one "See SCC status" link per business (no status shown).
5. Tests: update directories/builder tests; new: page totals == home card numbers, no per-business state on the Directories tab, proof-pending label, deep links.
6. Screenshots 390px + desktop from fixture data via local static server; prod count check by reading prod data (read only).
