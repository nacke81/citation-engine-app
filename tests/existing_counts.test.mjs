// t_d9ed56f5: an existing-confirmed listing (build_action existing) is NOT a new live listing in any count the engine feeds the client.
// Consumers of citation results: site/builder.js builderStats (home tiles, company page, weekly "went live" lines) and site/metrics.js weeklyMetrics (ce_weekly_metrics).
// No code in this repo reads the `deliverables` table (tests/deliverables_helper_test.py guards the writer); the client feed row is a title list, not a counter.
import test from "node:test";
import assert from "node:assert/strict";
import { builderRows, builderStats } from "../site/builder.js";
import { weeklyMetrics } from "../site/metrics.js";

const found = (d) => ({ biz: "SCC", directory: d, result: "found", diffs: null, url: "https://" + d + "/x" });
const PROOF = { proof_url: "https://a.com/l/1", proof_nap: "Senior Care Consulting | 1 Main St | 502-555-0101", proof_at: "2026-11-17T12:00:00Z", proof_nap_match: true };
const st = (d, o) => ({ domain: d, biz: "SCC", ...o });
const BEFORE = [st("n49.com", { queue_state: "live", build_action: "new", ...PROOF })];   // one real new listing already counted
const EXISTING = [st("maps.apple.com", { queue_state: "live", queue_kind: "fix", build_action: "existing", ...PROOF }),
                  st("n49-existing.com", { queue_state: "live", queue_kind: "fix", build_action: "existing", ...PROOF })];   // the two 11/17 rows, as the engine stores them
const checks = [found("n49.com"), found("maps.apple.com"), found("n49-existing.com")];

test("before/after: adding the two existing-confirmed rows leaves every new-listing count unchanged and raises only `existing`", () => {
  const before = builderStats(builderRows([checks[0]], BEFORE));   // the week before the two existing rows were recorded
  const after = builderStats(builderRows(checks, [...BEFORE, ...EXISTING]));
  console.log("before", JSON.stringify(before)); console.log("after ", JSON.stringify(after));
  for (const k of ["newLive", "claimed", "fixed", "toBuild", "waiting", "needsPerson"]) assert.equal(after[k], before[k], k);
  assert.equal(before.existing, 0); assert.equal(after.existing, 2);
  assert.equal(after.newLive, 1);
});

test("weekly metrics (ce_weekly_metrics) do not count existing rows as newLive/claimed/fixed", () => {
  const b = weeklyMetrics(checks, BEFORE, []), a = weeklyMetrics(checks, [...BEFORE, ...EXISTING], []);
  for (const k of ["newLive", "claimed", "fixed"]) assert.equal(a[k], b[k], k);
});

test("a wrong-NAP existing row is not a result at all (Waiting), still never new", () => {
  const s = builderStats(builderRows(checks, [...BEFORE, st("maps.apple.com", { queue_state: "live", build_action: "existing", ...PROOF, proof_nap_match: false })]));
  assert.equal(s.newLive, 1); assert.equal(s.existing, 0);
});
