// t_43e88fb7: weekly metrics. The snapshot uses the tiles' own functions; a past week that cannot be rebuilt is a gap (null), never a zero.
import test from "node:test";
import assert from "node:assert/strict";
import { overviewHtml } from "../site/render.js";
import { weeklyMetrics, rebuildMetrics, possibleQueueStates, pointsFor, METRICS, CHECK_KEYS, QUEUE_KEYS } from "../site/metrics.js";

const runs = [{ id: "r2", status: "ok", started_at: "2026-11-01T17:00:00Z", counts: {} }, { id: "r1", status: "ok", started_at: "2026-10-25T16:00:00Z", counts: {} }];
const ck = (biz, directory, result, extra = {}) => ({ biz, directory, result, run_id: "r2", diffs: [], ...extra });
const checks = [
  ck("SCC", "a.example", "found"), ck("SCC", "b.example", "found", { diffs: [{ field: "phone", live: "1", canonical: "2" }] }), ck("SCC", "c.example", "found"),
  ck("SCC", "d.example", "absent"), ck("SCC", "e.example", "couldnt_check"), ck("SCC", "f.example", "unsearchable"), ck("SCC", "g.example", "found"),
  ck("NM", "a.example", "found"), ck("NM", "b.example", "absent"), ck("NM", "c.example", "couldnt_check", { note: "blocked: cloudflare" }),
  ck("NM", "h.example", "found", { diffs: [{ field: "name", live: "x", canonical: "y" }] }),
  { ...ck("SCC", "old.example", "found"), run_id: "r1" },
];
const dirs = ["a", "b", "c", "d", "e", "f", "g", "h", "old"].map((x) => ({ domain: x + ".example", name: x, agent_access: "ok" }));
const proof = { proof_url: "https://a.example/p", proof_nap: "N A P", proof_at: "2026-10-30", proof_nap_match: true };
const dirStatus = [
  { biz: "SCC", domain: "a.example", queue_state: "live", queue_kind: "create", build_action: "new", claim_status: "claimed", ...proof },
  { biz: "SCC", domain: "b.example", queue_state: "submitted", queue_kind: "fix", build_action: "fix" },
  { biz: "SCC", domain: "c.example", queue_state: "needs-human", queue_kind: "fix" },
  { biz: "SCC", domain: "d.example", queue_state: "queued", queue_kind: "create", build_action: "new" },
  { biz: "SCC", domain: "g.example", claim_status: "claimed" },
  { biz: "NM", domain: "a.example", claim_status: "unknown" },
];
const dbs = { dirs, dirStatus, snapshots: [], weekly: [] };

const tile = (html, biz, id) => {
  const card = html.split('data-testid="biz-').find((s) => s.startsWith(biz + '"'));
  return Number(card.match(new RegExp(`data-testid="stat-${id}"[^>]*><b[^>]*>(\\d+)`))[1]);
};
const TILE_ID = { found: "found", notFound: "notfound", correct: "correct", withErrors: "errors", couldntCheck: "cant", checked: "checked", toBuild: "tobuild", waiting: "waiting", needsPerson: "needsperson", newLive: "newlive", claimed: "claimed", fixed: "fixed" };

test("12 metrics, tile labels and order", () => {
  assert.deepEqual(METRICS.map((m) => m[1]), ["Found", "Not found", "Correct", "With NAP errors", "Couldn't check", "Checked", "To build", "Waiting on directory", "Needs a person", "New listings live", "Claimed", "Fixed"]);
  assert.equal(CHECK_KEYS.length + QUEUE_KEYS.length, 12);
});

for (const biz of ["SCC", "NM"]) {
  test(`latest snapshot equals the tiles on screen: ${biz}`, () => {
    const html = overviewHtml(runs, checks, dbs);
    const cs = checks.filter((c) => c.run_id === "r2" && c.biz === biz);
    const m = weeklyMetrics(cs, dirStatus.filter((r) => r.biz === biz), dirs);
    for (const [k] of METRICS) assert.equal(m[k], tile(html, biz, TILE_ID[k]), `${biz} ${k}`);
  });
}
test("fixture is not degenerate: SCC has non-zero in-flight and result numbers", () => {
  const m = weeklyMetrics(checks.filter((c) => c.run_id === "r2" && c.biz === "SCC"), dirStatus.filter((r) => r.biz === "SCC"), dirs);
  assert.ok(m.waiting > 0 && m.needsPerson > 0 && m.toBuild > 0 && m.newLive > 0 && m.correct > 0 && m.withErrors > 0);
});

test("six check metrics rebuild from ce_checks with the same counts as the tiles", () => {
  const cs = checks.filter((c) => c.run_id === "r2" && c.biz === "SCC");
  const r = rebuildMetrics({ checks: cs, queueRows: [], status: [], dirs, runDay: "2026-11-01" });
  const live = weeklyMetrics(cs, [], dirs);
  for (const k of CHECK_KEYS) { assert.equal(r.metrics[k], live[k], k); assert.equal(r.sources[k], "ce_checks"); }
});

test("a week that cannot be rebuilt is a gap (null), not zero", () => {
  // NM has no queue. A found row's claim_status and a Directory's agent_access are current-only, so To build / Needs a person cannot be known.
  const cs = checks.filter((c) => c.run_id === "r2" && c.biz === "NM");
  const r = rebuildMetrics({ checks: cs, queueRows: [], status: [], dirs, runDay: "2026-10-25" });
  assert.equal(r.metrics.toBuild, null);
  assert.equal(r.sources.toBuild, "gap");
  assert.ok(r.ranges.toBuild[0] < r.ranges.toBuild[1]);
  assert.equal(r.metrics.needsPerson, null);
  assert.equal(JSON.stringify(r.metrics).includes('"toBuild":0'), false);
});
test("with no queue row every possible state maps to 0 waiting / results: those are exact", () => {
  const cs = checks.filter((c) => c.run_id === "r2" && c.biz === "NM");
  const r = rebuildMetrics({ checks: cs, queueRows: [], status: [], dirs, runDay: "2026-10-25" });
  for (const k of ["waiting", "newLive", "claimed", "fixed"]) { assert.equal(r.metrics[k], 0, k); assert.equal(r.sources[k], "queue history"); }
});
test("certain queue history gives an exact value", () => {
  const cs = [ck("SCC", "a.example", "found")];
  const q = [{ directory: "a.example", state: "live", kind: "create", history: [{ at: "2026-10-21", from: "queued", to: "submitted" }, { at: "2026-10-26", from: "submitted", to: "live" }] }];
  const r = rebuildMetrics({ checks: cs, queueRows: q, status: [dirStatus[0]], dirs, runDay: "2026-11-01" });
  assert.equal(r.metrics.newLive, 1); assert.equal(r.metrics.waiting, 0); assert.equal(r.sources.newLive, "queue history");
  // Same row on 10/24: submitted, so waiting 1 and no result yet.
  const early = rebuildMetrics({ checks: cs, queueRows: q, status: [dirStatus[0]], dirs, runDay: "2026-10-24" });
  assert.equal(early.metrics.waiting, 1); assert.equal(early.metrics.newLive, 0);
});
test("a move on the run day itself is ambiguous: gap, never a guess", () => {
  const cs = [ck("SCC", "a.example", "found")];
  const q = [{ directory: "a.example", state: "live", kind: "create", history: [{ at: "2026-10-21", from: "queued", to: "submitted" }, { at: "2026-11-01", from: "submitted", to: "live" }] }];
  const r = rebuildMetrics({ checks: cs, queueRows: q, status: [dirStatus[0]], dirs, runDay: "2026-11-01" });
  assert.equal(r.metrics.waiting, null); assert.equal(r.metrics.newLive, null); assert.equal(r.sources.newLive, "gap");
});
test("live row whose proof came later is still waiting that week", () => {
  const cs = [ck("SCC", "a.example", "found")];
  const q = [{ directory: "a.example", state: "live", kind: "create", history: [{ at: "2026-10-21", from: "queued", to: "live" }] }];
  const r = rebuildMetrics({ checks: cs, queueRows: q, status: [dirStatus[0]], dirs, runDay: "2026-10-25" });   // proof_at 10/30
  assert.equal(r.metrics.waiting, 1); assert.equal(r.metrics.newLive, 0);
});
test("possibleQueueStates: before-first-move, same-day and settled", () => {
  const h = [{ at: "2026-10-21", from: "queued", to: "needs-human" }, { at: "2026-10-26", from: "needs-human", to: "live" }];
  assert.deepEqual(possibleQueueStates(h, "2026-10-20", "live"), [null, "queued"]);
  assert.deepEqual(possibleQueueStates(h, "2026-10-25", "live"), ["needs-human"]);
  assert.deepEqual(possibleQueueStates(h, "2026-10-26", "live").sort(), ["live", "needs-human"]);
  assert.deepEqual(possibleQueueStates([], "2026-10-26", "found"), [null, "found"]);
});

test("pointsFor: one business, sorted by week, junk dropped", () => {
  const rows = [{ biz: "SCC", week_index: 1, captured_on: "2026-10-18", metrics: { found: 1 }, run_id: "x" }, { biz: "SCC", week_index: 0, captured_on: "2026-10-16", metrics: { found: 2 } }, { biz: "NM", week_index: 0, captured_on: "2026-10-16", metrics: {} }, { biz: "SCC", week_index: "z", metrics: {} }];
  assert.deepEqual(pointsFor(rows, "SCC").map((p) => [p.week, p.date]), [[0, "2026-10-16"], [1, "2026-10-18"]]);
});
