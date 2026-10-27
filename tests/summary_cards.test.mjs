import test from "node:test";
import assert from "node:assert/strict";
import { snapshotSummary, snapshotCardsHtml } from "../site/logic.js";
import { overviewHtml } from "../site/render.js";

const GOLD = { live: 19, inProgress: 9, napCorrect: 4, napChecked: 5, napFix: 5, blocked: 26, declined: 27 };
const snaps = [{ biz: "SCC", client_id: "x", captured_day: "2026-10-27", payload: { summary: GOLD, directories: [] } }];
const runs = [{ id: "r1", status: "ok", started_at: "2026-10-16T11:30:00Z", counts: {} }];
const checks = [{ biz: "SCC", directory: "a.example", result: "found", diffs: [], run_id: "r1" }];

test("cards: Live / In progress / NAP correct X of live / Declined, from the snapshot summary", () => {
  const html = snapshotCardsHtml(GOLD);
  assert.match(html, /data-testid="stat-live"[^>]*><b>19<\/b><span>Live</);
  assert.match(html, /data-testid="stat-inprogress"[^>]*><b>9<\/b><span>In progress</);
  assert.match(html, /data-testid="stat-napcorrect"[^>]*><b>4 of 19<\/b><span>NAP correct</);
  assert.match(html, /data-testid="stat-declined"[^>]*><b>27<\/b><span>Declined</);
  assert.match(html, /14 not read yet/);
});
test("cards: all read, no 'not read yet' note", () => {
  assert.ok(!/not read yet/.test(snapshotCardsHtml({ ...GOLD, napChecked: 19, napCorrect: 17 })));
});
test("snapshotSummary: only a complete integer summary is used; wrong business or missing fields fall back", () => {
  assert.deepEqual(snapshotSummary(snaps, "SCC"), GOLD);
  assert.equal(snapshotSummary(snaps, "NM"), null);
  assert.equal(snapshotSummary([{ biz: "SCC", payload: { summary: { live: 1 } } }], "SCC"), null);
  assert.equal(snapshotSummary([{ biz: "SCC", payload: { found: 11, couldntCheck: 14 } }], "SCC"), null);
  assert.equal(snapshotSummary(undefined, "SCC"), null);
});
test("overview: SCC shows the four snapshot cards and no stale Found / Couldn't check cards", () => {
  const html = overviewHtml(runs, checks, { snapshots: snaps });
  const scc = html.slice(html.indexOf('data-testid="biz-SCC"'), html.indexOf('data-testid="biz-NM"'));
  for (const id of ["stat-live", "stat-inprogress", "stat-napcorrect", "stat-declined"]) assert.ok(scc.includes(`data-testid="${id}"`), id);
  for (const id of ["stat-found", "stat-notfound", "stat-correct", "stat-errors", "stat-cant", "stat-checked"]) assert.ok(!scc.includes(`data-testid="${id}"`), id);
  assert.ok(!/Couldn't check|Found</.test(scc.split("In flight")[0]));
});
test("overview: no snapshot loaded -> the scan cards still render (fallback)", () => {
  const html = overviewHtml(runs, checks, { snapshots: [] });
  assert.ok(html.includes('data-testid="stat-found"') && !html.includes('data-testid="stat-live"'));
});
