# 2026-11-04: collapsible sections on the business pages (t_3a7fdcfe)

Cites latest lesson: docs/lessons/2026-11-03-two-comparators-looser-wins.md (one source of truth per decision). Here: one `secOpen` default rule, used by render and tests; no second copy in app.js.

## Scope
UI only. No data/logic change. Files: site/render.js, site/app.js, site/index.html, tests/collapse.test.mjs.

## Design
- Each of the 9 sections (To build, Waiting, Needs a person, New live, Claimed, Fixed, Found, Not found, Couldn't check) = `<section data-sec=id>` with a heading containing `<button aria-expanded aria-controls>` (chevron + name + count) and a `.cbody` div (`hidden` when closed).
- Existing ids/testids (grp-*, found-title, cant-title, grp-*-n) stay on the heading/count.
- Default: only `needsperson` open (no clear primary section otherwise). Saved map `{id:bool}` overrides.
- "Expand all"/"Collapse all" buttons above sections.
- localStorage key `ce-sec:<biz>`; try/catch so blocked storage falls back to defaults.
- Deep link (#SCC/<id> or directory) opens its section before scrolling.

## Tests
render: default open/closed, saved map override, counts visible in button, aria-controls matches body id, expand/collapse buttons, bad saved values ignored, existing rows still rendered while hidden. Existing npm test must stay green.
