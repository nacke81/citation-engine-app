import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { filterDirs, sortDirs, bizStatus, directoriesHtml, detailHtml, tabsHtml, DEFAULT_FILTERS } from "../site/directories.js";

const SEED = JSON.parse(readFileSync(new URL("../db/directories_seed.json", import.meta.url), "utf8"));
const by = Object.fromEntries(SEED.map((d) => [d.domain, d]));

test("seed has 86 Directories and the list renders all 86", () => {
  assert.equal(SEED.length, 86);
  const h = directoriesHtml(SEED, []);
  assert.equal((h.match(/class="row dir/g) || []).length, 86);
  assert.match(h, /86 of 86/);
});
test("filters: build route, agent access, cost, checked weekly", () => {
  assert.deepEqual(filterDirs(SEED, { ...DEFAULT_FILTERS, route: "agency-account" }).map((d) => d.domain), ["bing.com"]);
  assert.deepEqual(filterDirs(SEED, { ...DEFAULT_FILTERS, access: "blocked" }).map((d) => d.domain).sort(), ["acompio.us", "bing.com", "superpages.com", "yellowpages.com"]);
  assert.ok(filterDirs(SEED, { ...DEFAULT_FILTERS, cost: "paid" }).every((d) => d.cost === "paid"));
  assert.equal(filterDirs(SEED, { ...DEFAULT_FILTERS, weekly: "y" }).length, 35);
  assert.equal(filterDirs(SEED, { ...DEFAULT_FILTERS, weekly: "n" }).length, 51);
  assert.deepEqual(filterDirs(SEED, { ...DEFAULT_FILTERS, q: "YELLOWBOT" }).map((d) => d.domain), ["yellowbot.com"]);
  assert.equal(filterDirs(SEED, { ...DEFAULT_FILTERS, route: "agent", access: "blocked", weekly: "y" }).length, 3);
});
test("sort: access puts blocked first, name is alphabetical, priority keeps weekly-25 first", () => {
  assert.equal(sortDirs(SEED, "access")[0].agent_access, "blocked");
  const names = sortDirs(SEED, "name").map((d) => d.name);
  assert.deepEqual(names, names.slice().sort((a, b) => a.localeCompare(b)));
  assert.equal(sortDirs(SEED, "priority")[0].priority, 1);
});
test("a row opens to show everything known plus each business's status", () => {
  const rows = [{ domain: "yelp.com", biz: "SCC", last_result: "found", last_checked_on: "2026-10-21", claim_status: "unknown", queue_state: "needs-human", queue_note: "Yelp wants a phone code", last_url: "https://www.yelp.com/biz/x" },
                { domain: "yelp.com", biz: "NM", last_result: "absent", last_checked_on: "2026-10-21" }];
  const h = directoriesHtml(SEED, rows, DEFAULT_FILTERS, "yelp.com");
  assert.match(h, /data-testid="detail-yelp.com"/);
  assert.match(h, /Yelp wants a phone code/);
  for (const k of ["Category", "Search method", "Zero-result marker", "Claim markers", "Cost", "Account needed", "Verification", "Build route", "Agent access", "Last verified"]) assert.ok(h.includes(k), k);
  assert.match(h, /data-testid="status-yelp.com-SCC"/);
  assert.match(h, /data-testid="status-yelp.com-NM"/);
  assert.match(h, /Not found/);   // NM absent shows as Not found, never the old word
  assert.ok(!/absent/i.test(h), "the word absent must not be shown");
});
test("Bing shows the agency account route and GBP sync", () => {
  const h = detailHtml(by["bing.com"], []);
  assert.match(h, /Mike agency account/);
  assert.match(h, /GBP sync/);
});
test("a Directory blocked for the agent shows needs-human with its reason", () => {
  const s = bizStatus(by["yellowpages.com"], { last_result: "couldnt_check" });
  assert.equal(s.state, "needs-human");
  assert.match(s.reason, /Cloudflare/);
  assert.equal(bizStatus(by["yelp.com"], null).state, null);
  assert.equal(bizStatus(by["yelp.com"], { queue_state: "live" }).state, "live");
  assert.equal(bizStatus(by["acompio.us"], { queue_state: "queued" }).state, "needs-human");
  assert.match(directoriesHtml(SEED, [], DEFAULT_FILTERS, "acompio.us"), /Turnstile/);
});
test("unsafe URLs and markup are escaped", () => {
  const d = { ...by["yelp.com"], domain: "x.test", name: "<img src=x onerror=1>", signup_url: "javascript:alert(1)" };
  const h = directoriesHtml([d], [], DEFAULT_FILTERS, "x.test");
  assert.ok(!h.includes("<img src=x"));
  assert.ok(!h.includes("javascript:"));
});
test("empty state and no-match state", () => {
  assert.match(directoriesHtml([], []), /dirs-empty/);
  assert.match(directoriesHtml(SEED, [], { ...DEFAULT_FILTERS, q: "zzzz" }), /dirs-none/);
});
test("tabs: Directories sits next to the business tabs and marks the active one", () => {
  const h = tabsHtml("directories", [{}]);
  assert.match(h, /tab-SCC/); assert.match(h, /tab-NM/); assert.match(h, /tab-directories/);
  assert.match(h, /tab on"[^>]*data-testid="tab-directories"/);
  assert.ok(h.indexOf("tab-NM") < h.indexOf("tab-directories"));
});
test("no client name, street or phone in the served Directory view", () => {
  const h = directoriesHtml(SEED, [], DEFAULT_FILTERS, "yelp.com") + SEED.map((d) => detailHtml(d, [])).join("");
  assert.ok(!/\b\d{3}[\s.\-)]*\d{3}[\s.\-]*\d{4}\b/.test(h.replace(/\d{4}-\d{2}-\d{2}/g, "")), "no phone-shaped number");
});
