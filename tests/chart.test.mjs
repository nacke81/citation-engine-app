// t_43e88fb7: the weekly chart. Gaps are drawn as gaps, a toggle hides and restores its line and survives a reload, tiles keep click-to-filter.
import test from "node:test";
import assert from "node:assert/strict";
import { chartHtml, chartSvg, loadHidden, saveHidden, toggleHidden, wireChart, chartKey, driftNote } from "../site/chart.js";
import { overviewHtml } from "../site/render.js";
import { METRICS } from "../site/metrics.js";

const full = (n) => Object.fromEntries(METRICS.map(([k], i) => [k, n + i]));
const points = [
  { week: 0, date: "2026-10-16", metrics: { ...full(1), toBuild: null, needsPerson: null } },
  { week: 1, date: "2026-10-18", metrics: { ...full(2), toBuild: null } },
  { week: 2, date: "2026-10-25", metrics: { ...full(3) } },
  { week: 3, date: "2026-11-01", metrics: { ...full(3), found: null } },
];
const memStore = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m }; };

test("X axis: one label per weekly point, Wk N plus date", () => {
  const svg = chartSvg(points);
  for (const [w, d] of [[0, "10/16"], [1, "10/18"], [2, "10/25"], [3, "11/01"]]) { assert.ok(svg.includes(`>Wk ${w}</text>`), `Wk ${w}`); assert.ok(svg.includes(`>${d}</text>`), d); }
});
test("hover: every plotted point carries week, date, label and value", () => {
  const svg = chartSvg(points);
  assert.match(svg, /<title>Wk 2 · 2026-10-25 · Found: 3<\/title>/);
  assert.match(svg, /<title>Wk 3 · 2026-11-01 · Fixed: 14<\/title>/);
});
test("a gap is a gap: no point, no zero, and the line breaks", () => {
  const svg = chartSvg(points);
  assert.equal(svg.includes("To build: 0"), false);
  assert.equal((svg.match(/data-testid="pt-toBuild-/g) || []).length, 2);          // weeks 2 and 3 only
  assert.equal((svg.match(/data-testid="pt-found-/g) || []).length, 3);            // week 3 is null
  const g = svg.match(/<g data-line="notFound".*?<\/g>/)[0];
  assert.equal((g.match(/M/g) || []).length, 1);                                   // continuous series: one stroke
  const broken = chartSvg([{ week: 0, date: "2026-10-16", metrics: full(1) }, { week: 1, date: "2026-10-18", metrics: { ...full(1), found: null } }, { week: 2, date: "2026-10-25", metrics: full(1) }]);
  assert.equal((broken.match(/<g data-line="found".*?<\/g>/)[0].match(/M/g) || []).length, 2);   // gap in the middle lifts the pen
});
test("one line per tile, 12 legend checkboxes, all on by default", () => {
  const h = chartHtml("SCC", points);
  assert.equal((h.match(/<g data-line=/g) || []).length, 12);
  assert.equal((h.match(/<input type="checkbox" data-metric=/g) || []).length, 12);
  assert.equal((h.match(/<input type="checkbox"[^>]* checked>/g) || []).length, 12);
  for (const [, label] of METRICS) assert.ok(h.includes(`</i>${label.replace("'", "&#39;")}</label>`), label);
  assert.equal(h.includes("display:none"), false);
});
test("toggle hides and restores its line, and the choice survives a reload (per business)", () => {
  const st = memStore();
  let hidden = toggleHidden(loadHidden(st, "SCC"), "claimed");
  hidden = toggleHidden(hidden, "fixed");
  saveHidden(st, "SCC", hidden);
  // reload: fresh load from storage
  const reloaded = chartHtml("SCC", points, loadHidden(st, "SCC"));
  assert.match(reloaded, /<g data-line="claimed"[^>]*style="display:none"/);
  assert.match(reloaded, /<g data-line="fixed"[^>]*style="display:none"/);
  assert.match(reloaded, /data-metric="claimed" data-testid="tog-claimed">/);          // unchecked: no 'checked' attr
  assert.equal((reloaded.match(/<input type="checkbox"[^>]* checked>/g) || []).length, 10);
  assert.equal(loadHidden(st, "NM").length, 0);                                         // other business untouched
  assert.ok(st.m.has(chartKey("SCC")));
  // restore
  saveHidden(st, "SCC", toggleHidden(toggleHidden(loadHidden(st, "SCC"), "claimed"), "fixed"));
  assert.equal(chartHtml("SCC", points, loadHidden(st, "SCC")).includes("display:none"), false);
});
test("junk or blocked storage falls back to all on", () => {
  assert.deepEqual(loadHidden({ getItem: () => "{not json" }, "SCC"), []);
  assert.deepEqual(loadHidden({ getItem: () => { throw new Error("blocked"); } }, "SCC"), []);
  assert.deepEqual(loadHidden({ getItem: () => JSON.stringify(["found", "nope", 3]) }, "SCC"), ["found"]);
  assert.doesNotThrow(() => saveHidden({ setItem: () => { throw new Error("blocked"); } }, "SCC", ["found"]));
});

// Minimal DOM: just enough for wireChart's click path.
function fakeBox() {
  const mk = () => ({ style: { display: "" }, listeners: {}, addEventListener(t, f) { this.listeners[t] = f; } });
  const inputs = METRICS.map(([k]) => Object.assign(mk(), { dataset: { metric: k }, checked: true }));
  const groups = Object.fromEntries(METRICS.map(([k]) => [k, mk()]));
  const plot = { innerHTML: "", clientWidth: 700 };
  const box = { querySelectorAll: (s) => (s === "input[data-metric]" ? inputs : []), querySelector: (s) => (s === ".wplot" ? plot : (s.match(/data-line="(\w+)"/) ? groups[s.match(/data-line="(\w+)"/)[1]] : null)) };
  return { root: { querySelector: () => box }, inputs, groups };
}
test("wireChart: clicking a legend checkbox hides then shows its line and saves it", () => {
  const st = memStore(), { root, inputs, groups } = fakeBox();
  wireChart(root, "SCC", points, st);
  const found = inputs.find((i) => i.dataset.metric === "found");
  found.checked = false; found.listeners.change();
  assert.equal(groups.found.style.display, "none");
  assert.equal(groups.notFound.style.display, "");
  assert.deepEqual(loadHidden(st, "SCC"), ["found"]);
  found.checked = true; found.listeners.change();
  assert.equal(groups.found.style.display, "");
  assert.deepEqual(loadHidden(st, "SCC"), []);
});

const runs = [{ id: "r2", status: "ok", started_at: "2026-11-01T17:00:00Z", counts: {} }];
const checks = [{ biz: "SCC", directory: "a.example", result: "found", run_id: "r2", diffs: [] }, { biz: "NM", directory: "a.example", result: "found", run_id: "r2", diffs: [] }];
test("home page: chart sits under the business name and above the tiles; tiles stay links", () => {
  const html = overviewHtml(runs, checks, { weekly: [{ biz: "SCC", run_id: "r2", week_index: 0, captured_on: "2026-11-01", metrics: full(1) }], dirs: [], dirStatus: [] });
  const card = (b) => html.split('data-testid="biz-').find((s) => s.startsWith(b + '"'));
  for (const b of ["SCC", "NM"]) {   // every business, not only SCC
    const c = card(b);
    assert.ok(c.indexOf("<h2>") < c.indexOf('data-testid="weekly-chart"'), b);
    assert.ok(c.indexOf('data-testid="weekly-chart"') < c.indexOf('<div class="stats">'), b);
    assert.match(c, /<a class="stat" href="#[A-Z]+\/found" data-testid="stat-found">/);       // click-to-filter unchanged
  }
  assert.match(card("NM"), /No weekly history yet\./);
});
test("drift note appears only when the tiles moved since the same run's snapshot", () => {
  const pts = [{ week: 3, date: "2026-11-01", runId: "r2", metrics: full(1) }];
  assert.equal(driftNote(pts, full(1), "r2"), "");
  assert.match(driftNote(pts, { ...full(1), waiting: 99 }, "r2"), /Waiting on directory 8 to 99/);
  assert.equal(driftNote(pts, { ...full(1), waiting: 99 }, "other"), "");
});
test("readable at card width and on mobile: svg scales, no fixed overflow", () => {
  for (const w of [700, 390, 320]) { const s = chartSvg(points, [], w); assert.match(s, new RegExp(`viewBox="0 0 ${w} \\d+"`)); assert.match(s, /max-width:100%/); }
  const many = Array.from({ length: 26 }, (_, i) => ({ week: i, date: "2026-10-16", metrics: full(1) }));
  assert.ok((chartSvg(many, [], 320).match(/>Wk \d+</g) || []).length < 26);               // labels thin out instead of overlapping
});
