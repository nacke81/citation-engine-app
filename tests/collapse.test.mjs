import test from "node:test";
import assert from "node:assert/strict";
import { bizHtml, secOpen } from "../site/render.js";

const runs = [{ id: "r1", status: "ok", started_at: "2026-10-16T11:30:00Z", counts: {} }];
const checks = [
  { biz: "SCC", directory: "a.example", result: "found", diffs: [], run_id: "r1" },
  { biz: "SCC", directory: "b.example", result: "couldnt_check", diffs: [], run_id: "r1", reason: "blocked" },
];
const IDS = ["tobuild", "waiting", "needsperson", "newlive", "claimed", "fixed", "found", "notfound", "cant"];
const btn = (html, id) => html.match(new RegExp(`<button[^>]*aria-controls="body-${id}"[^>]*>`))[0];
const body = (html, id) => html.match(new RegExp(`<div class="cbody" id="body-${id}"([^>]*)>`))[1];

test("default: only Needs a person is open", () => {
  const h = bizHtml(runs, checks, "SCC", {});
  for (const id of IDS) {
    const open = id === "needsperson";
    assert.match(btn(h, id), new RegExp(`aria-expanded="${open}"`), id);
    assert.equal(body(h, id).includes("hidden"), !open, id);
  }
});
test("saved state overrides the default, per section; junk values are ignored", () => {
  const h = bizHtml(runs, checks, "SCC", {}, { needsperson: false, cant: true, found: "yes", fixed: 1 });
  assert.match(btn(h, "needsperson"), /aria-expanded="false"/);
  assert.match(btn(h, "cant"), /aria-expanded="true"/);
  assert.match(btn(h, "found"), /aria-expanded="false"/);
  assert.equal(secOpen(null, "needsperson"), true);
  assert.equal(secOpen(undefined, "cant"), false);
});
test("header button keeps name and count when collapsed; rows still in the markup", () => {
  const h = bizHtml(runs, checks, "SCC", {});
  assert.match(h, /<button[^>]*aria-controls="body-cant"[^>]*>.*?Couldn&#39;t check <span class="n">1<\/span><\/button>/);
  assert.match(h, /data-testid="cant-b.example"/);
  assert.match(h, /id="grp-cant"/);
});
test("Expand all / Collapse all controls are on the page", () => {
  const h = bizHtml(runs, checks, "SCC", {});
  assert.match(h, /data-expand="all"[^>]*>Expand all</);
  assert.match(h, /data-expand="none"[^>]*>Collapse all</);
});
test("every section is a real button with aria-expanded and a matching controlled id", () => {
  const h = bizHtml(runs, checks, "SCC", {});
  assert.equal((h.match(/<button type="button" class="tog"/g) || []).length, IDS.length);
  for (const id of IDS) assert.ok(h.includes(`id="body-${id}"`), id);
});
test("unknown business still returns null", () => {
  assert.equal(bizHtml(runs, checks, "ZZZ", {}), null);
});
