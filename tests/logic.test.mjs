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

import { fixList, absentList, cantCheckLine } from "../site/logic.js";
const stale = { result: "found", directory: "a.example", url: "https://a.example/x", diffs: [{ field: "phone", live: "(615) 555-0112", canonical: "(615) 555-0111" }] };
const clean = { result: "found", directory: "b.example", url: "https://b.example/x", diffs: [] };
const old = { result: "found", directory: "c.example", url: "https://c.example/x", diffs: null };
const cc = { result: "couldnt_check", directory: "d.example" };
const un = { result: "unsearchable", directory: "e.example" };
const ab = { result: "absent", directory: "f.example" };
test("golden: stale phone listing is on the fix list with the right field and URL", () => {
  const f = fixList([stale, clean, old, cc, un, ab]);
  assert.equal(f.length, 1);
  assert.deepEqual(f[0], { directory: "a.example", url: "https://a.example/x", field: "phone", live: "(615) 555-0112", canonical: "(615) 555-0111" });
});
test("golden: a matching listing and a listing with no diffs recorded are not on the fix list", () => {
  assert.equal(fixList([clean, old]).length, 0);
});
test("golden: a couldn't-check or unsearchable row never shows as absent, and never on the fix list", () => {
  assert.deepEqual(absentList([cc, un, { result: "banana", directory: "g.example" }, { directory: "h.example" }]), []);
  assert.deepEqual(absentList([cc, ab]).map((x) => x.directory), ["f.example"]);
  assert.equal(fixList([{ ...cc, diffs: [{ field: "phone", live: "x", canonical: "y" }] }]).length, 0);
});
test("self-check: a found row wrongly tagged absent would be caught by the absent assertion", () => {
  assert.notDeepEqual(absentList([{ result: "absent", directory: "z.example" }]), []);
});
test("count line covers couldn't check plus unsearchable only", () => {
  assert.equal(cantCheckLine([cc, un, ab, stale]), "2 couldn't check");
});
