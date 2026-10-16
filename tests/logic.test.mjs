import test from "node:test";
import assert from "node:assert/strict";
import { statusOf, counts, matchLabel, sortChecks, latestFor, windowLine, LABEL } from "../site/logic.js";

test("unknown or missing result is couldn't check, never absent", () => {
  assert.equal(statusOf({ result: "banana" }), "couldnt_check");
  assert.equal(statusOf(undefined), "couldnt_check");
  assert.equal(statusOf({ result: null }), "couldnt_check");
});
test("absent only shows when the job said absent", () => {
  assert.equal(statusOf({ result: "absent" }), "absent");
  assert.equal(counts([{ result: "couldnt_check" }, { result: "unsearchable" }]).absent, 0);
});
test("unsearchable keeps its own label", () => {
  assert.equal(LABEL.unsearchable, "Couldn't check (unsearchable)");
});
test("match label only on found rows", () => {
  assert.equal(matchLabel({ result: "found", match: true }), "Match: Y");
  assert.equal(matchLabel({ result: "found", match: false }), "Match: N");
  assert.equal(matchLabel({ result: "absent", match: true }), "");
});
test("sort puts found first, then absent, then couldn't check", () => {
  const s = sortChecks([{ result: "couldnt_check", directory: "a" }, { result: "found", directory: "z" }, { result: "absent", directory: "m" }]);
  assert.deepEqual(s.map((x) => x.result), ["found", "absent", "couldnt_check"]);
});
test("latest run only, per business", () => {
  const runs = [{ id: "r2" }, { id: "r1" }];
  const checks = [{ run_id: "r1", biz: "SCC" }, { run_id: "r2", biz: "SCC" }, { run_id: "r2", biz: "NM" }];
  assert.equal(latestFor(runs, checks, "SCC").checks.length, 1);
  assert.equal(latestFor([], checks, "SCC").run, null);
});
test("window line flags unequal counts and a live owned pid", () => {
  assert.match(windowLine({ chrome_before: 3, chrome_during: 4, chrome_after: 3, chrome_equal: true, owned_alive_after: [] }), /\(equal\); owned_alive_after empty/);
  assert.match(windowLine({ chrome_before: 3, chrome_during: 4, chrome_after: 4, chrome_equal: false, owned_alive_after: [9] }), /NOT equal.*9/);
});
