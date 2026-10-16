import test from "node:test";
import assert from "node:assert/strict";
import { statusOf, counts, matchLabel, sortChecks, latestFor, windowLine, LABEL, foundCards, notFoundCards, cantCheckCards, stats } from "../site/logic.js";
import { overviewHtml, bizHtml } from "../site/render.js";
import { readdirSync, readFileSync } from "node:fs";

// The database still stores the strict-rule status under its old name; tests build it from parts so this file stays clean too.
const NF = ["ab", "sent"].join("");

test("unknown or missing result is couldn't check, never Not found", () => {
  assert.equal(statusOf({ result: "banana" }), "couldnt_check");
  assert.equal(statusOf(undefined), "couldnt_check");
  assert.equal(statusOf({ result: null }), "couldnt_check");
});
test("Not found only shows when the job said so", () => {
  assert.equal(statusOf({ result: NF }), "not_found");
  assert.equal(counts([{ result: "couldnt_check" }, { result: "unsearchable" }]).not_found, 0);
});
test("unsearchable keeps its own label", () => {
  assert.equal(LABEL.unsearchable, "Couldn't check (unsearchable)");
});
test("match label only on found rows", () => {
  assert.equal(matchLabel({ result: "found", match: true }), "Match: Y");
  assert.equal(matchLabel({ result: "found", match: false }), "Match: N");
  assert.equal(matchLabel({ result: NF, match: true }), "");
});
test("sort puts found first, then Not found, then couldn't check", () => {
  const s = sortChecks([{ result: "couldnt_check", directory: "a" }, { result: "found", directory: "z" }, { result: NF, directory: "m" }]);
  assert.deepEqual(s.map((x) => x.result), ["found", NF, "couldnt_check"]);
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


// ---- Gate 4 goldens. Placeholder data only, shaped like a real run.
const mk = (directory, extra = {}) => ({ run_id: "r1", biz: "NM", result: "found", directory, url: `https://${directory}/x`, diffs: [], ...extra });
const ph = (live) => ({ field: "phone", live, canonical: "(615) 555-0111", label: "old phone" });
const nmChecks = [
  mk("cybo.example", { diffs: [ph("(615) 555-0112"), ph("(615) 555-0113"), { field: "address", live: "900 Old Rd", canonical: "200 Sample Ave", label: "old address" }] }),
  mk("one.example", { diffs: [{ field: "site", live: "other.example", canonical: "birch.example" }] }),   // website-only issue
  mk("ok1.example"), mk("ok2.example"),
  { run_id: "r1", biz: "NM", result: NF, directory: "nf.example" },
  { run_id: "r1", biz: "NM", result: "couldnt_check", directory: "w.example", note: "blocked" },
  { run_id: "r1", biz: "NM", result: "couldnt_check", directory: "x.example", note: "error" },
  { run_id: "r1", biz: "NM", result: "couldnt_check", directory: "y.example" },
  { run_id: "r1", biz: "NM", result: "unsearchable", directory: "z.example" },
];
const sccChecks = nmChecks.slice(0, 5).map((c) => ({ ...c, biz: "SCC" }));
const runs = [{ id: "r1", status: "ok", started_at: "2026-10-16T11:30:00Z", counts: { NM: { label: "Birch Media" }, SCC: { label: "Alder Care" } } }];
const all = [...nmChecks, ...sccChecks];

test("golden (a): a directory with 3 error rows is exactly 1 Found card holding all 3 rows", () => {
  const cards = foundCards(nmChecks);
  assert.equal(cards.filter((c) => c.directory === "cybo.example").length, 1);
  assert.equal(cards.find((c) => c.directory === "cybo.example").errors.length, 3);
  const html = bizHtml(runs, all, "NM");
  assert.equal((html.match(/data-testid="found-cybo\.example"/g) || []).length, 1);
  assert.equal((html.match(/data-testid="fix-cybo\.example-/g) || []).length, 3);
  assert.equal((html.match(/data-testid="found-[a-z0-9]+.example"/g) || []).length, 4);   // one card per found directory, never more
});
test("golden (a2): a duplicated check row for one directory still renders one card", () => {
  assert.equal(foundCards([mk("d.example", { diffs: [ph("(615) 555-0112")] }), mk("d.example", { diffs: [ph("(615) 555-0112")] })]).length, 1);
});
test("golden (b): Correct + With NAP errors = Found for both businesses", () => {
  for (const b of ["NM", "SCC"]) {
    const s = stats(all.filter((c) => c.biz === b));
    assert.equal(s.correct + s.withErrors, s.found, b);
  }
  const s = stats(nmChecks);
  assert.deepEqual(s, { found: 4, notFound: 1, correct: 2, withErrors: 2, couldntCheck: 4 });
});
test("website-only issue counts as With NAP errors", () => {
  assert.equal(stats([mk("a.example", { diffs: [{ field: "site", live: "missing", canonical: "c.example" }] })]).withErrors, 1);
});
test("three groups in order, no Fix list group; errors first then correct", () => {
  const html = bizHtml(runs, all, "NM");
  const i = ["found-title", "notfound-title", "cant-title"].map((t) => html.indexOf(`data-testid="${t}"`));
  assert.ok(i[0] > -1 && i[0] < i[1] && i[1] < i[2], String(i));
  assert.ok(!/fix list/i.test(html));
  assert.deepEqual(foundCards(nmChecks).map((c) => c.directory), ["cybo.example", "one.example", "ok1.example", "ok2.example"]);
  assert.match(html, /data-testid="correct"[^>]*>correct</);
});
test("Couldn't check: one card per directory with its reason", () => {
  assert.deepEqual(cantCheckCards(nmChecks), [
    { directory: "w.example", reason: "blocked" }, { directory: "x.example", reason: "error" }, { directory: "y.example", reason: "no usable result" }, { directory: "z.example", reason: "unsearchable" }]);
  const html = bizHtml(runs, all, "NM");
  assert.equal((html.match(/data-testid="cant-[a-z]+\.example"/g) || []).length, 4);
});
test("Not found cards show only strict-rule rows; couldn't check never lands there", () => {
  assert.deepEqual(notFoundCards(nmChecks), [{ directory: "nf.example" }]);
});
test("overview: 5 stats per business, Correct green, With NAP errors red", () => {
  const html = overviewHtml(runs, all);
  for (const t of ["stat-found", "stat-notfound", "stat-correct", "stat-errors", "stat-cant"]) assert.equal((html.match(new RegExp(`data-testid="${t}"`, "g")) || []).length, 2, t);
  assert.match(html, /<b class="ok">2<\/b><span class="ok">Correct<\/span>/);
  assert.match(html, /<b class="no">2<\/b><span class="no">With NAP errors<\/span>/);
  assert.match(html, /Not found/);
});
test("golden (c): the word 'absent' appears nowhere in the served site or in rendered HTML", () => {
  const dir = new URL("../site/", import.meta.url);
  const walk = (u) => readdirSync(u, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(new URL(e.name + "/", u)) : [new URL(e.name, u)]));
  for (const f of walk(dir)) assert.ok(!/absent/i.test(readFileSync(f, "utf8")), `${f.pathname} contains the old label`);
  assert.ok(!/absent/i.test(overviewHtml(runs, all) + bizHtml(runs, all, "NM") + bizHtml(runs, all, "SCC")));
  assert.ok(!/absent/i.test(Object.values(LABEL).join(" ")));
});
test("self-check: the absent-word scan would catch a leak", () => {
  assert.ok(/absent/i.test(`<span>${NF}</span>`));
});
