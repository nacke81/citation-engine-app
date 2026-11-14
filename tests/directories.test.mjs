import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { filterDirs, sortDirs, directoriesHtml, detailHtml, tabsHtml, DEFAULT_FILTERS } from "../site/directories.js";

const SEED = JSON.parse(readFileSync(new URL("../db/directories_seed.json", import.meta.url), "utf8"));
const by = Object.fromEntries(SEED.map((d) => [d.domain, d]));

test("seed has 160 Directories and the list renders all 160", () => {
  assert.equal(SEED.length, 160);
  assert.equal(new Set(SEED.map((d) => d.domain)).size, 160);
  const h = directoriesHtml(SEED, []);
  assert.equal((h.match(/class="row dir/g) || []).length, 160);
  assert.match(h, /160 of 160/);
});
test("filters: build route, agent access, cost, checked weekly", () => {
  assert.deepEqual(filterDirs(SEED, { ...DEFAULT_FILTERS, route: "agency-account" }).map((d) => d.domain), ["bing.com"]);
  assert.deepEqual(filterDirs(SEED, { ...DEFAULT_FILTERS, access: "blocked" }).map((d) => d.domain).filter((x) => !by[x].cut.startsWith("cycle")).sort(), ["acompio.us", "bing.com", "superpages.com", "yellowpages.com"]);
  assert.equal(filterDirs(SEED, { ...DEFAULT_FILTERS, access: "blocked" }).length, 25);
  assert.ok(filterDirs(SEED, { ...DEFAULT_FILTERS, cost: "paid" }).every((d) => d.cost === "paid"));
  assert.equal(filterDirs(SEED, { ...DEFAULT_FILTERS, weekly: "y" }).length, 35);
  assert.equal(filterDirs(SEED, { ...DEFAULT_FILTERS, weekly: "n" }).length, 125);
  assert.deepEqual(filterDirs(SEED, { ...DEFAULT_FILTERS, q: "YELLOWBOT" }).map((d) => d.domain), ["yellowbot.com"]);
  assert.equal(filterDirs(SEED, { ...DEFAULT_FILTERS, route: "agent", access: "blocked", weekly: "y" }).length, 3);
});
test("sort: access puts blocked first, name is alphabetical, priority keeps weekly-25 first", () => {
  assert.equal(sortDirs(SEED, "access")[0].agent_access, "blocked");
  const names = sortDirs(SEED, "name").map((d) => d.name);
  assert.deepEqual(names, names.slice().sort((a, b) => a.localeCompare(b)));
  assert.equal(sortDirs(SEED, "priority")[0].priority, 1);
});
test("a row opens to show every Directory fact and no per-business state", () => {
  const rows = [{ domain: "yelp.com", biz: "SCC", last_result: "found", last_checked_on: "2026-10-21", claim_status: "unknown", queue_state: "needs-human", queue_note: "Yelp wants a phone code", last_url: "https://www.yelp.com/biz/x" },
                { domain: "yelp.com", biz: "NM", last_result: "absent", last_checked_on: "2026-10-21" }];
  const h = directoriesHtml(SEED, rows, DEFAULT_FILTERS, "yelp.com");
  assert.match(h, /data-testid="detail-yelp.com"/);
  for (const k of ["Category", "Search method", "Zero-result marker", "Claim markers", "Cost", "Account needed", "Verification", "Build route", "Agent access", "Last verified"]) assert.ok(h.includes(k), k);
  // client data lives on the company page
  assert.ok(!/Yelp wants a phone code/.test(h), "queue note must not show");
  assert.ok(!/data-testid="(status|row)-yelp.com-/.test(h), "no per-business blocks or chips");
  assert.ok(!/class="bzs"|bizstat|Last check|Check note|Needs human|Queued|Not checked/.test(h), "no per-business state markup");
  assert.ok(!h.includes("https://www.yelp.com/biz/x"), "no client listing URL");
  assert.match(h, /href="#SCC\/yelp.com"/); assert.match(h, /href="#NM\/yelp.com"/);
});
test("Bing shows the agency account route and GBP sync", () => {
  const h = detailHtml(by["bing.com"], []);
  assert.match(h, /Mike agency account/);
  assert.match(h, /GBP sync/);
});
test("a blocked Directory shows its blocker as a Directory fact", () => {
  assert.match(directoriesHtml(SEED, [], DEFAULT_FILTERS, "acompio.us"), /Turnstile/);
  assert.match(directoriesHtml(SEED, [], DEFAULT_FILTERS, "yellowpages.com"), /Cloudflare/);
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

// ---- Playbooks section (t_2cb780c2) ----
import { playbooksHtml, PLAYBOOK_TASKS } from "../site/directories.js";
const TT = { domain: "thumbtack.com", task: "verify", version: 1, send_is_signup: true, source: "run t_9de1c978", last_proven_at: "2026-11-13T18:00:00Z", stale: false,
  steps: [{ text: "Open the pro signup", url: "https://www.thumbtack.com/pro/signup?category_pk=136256193386480124&zipcode=37066", selector: "#email" }, { text: "Click Continue", selector: "button[type=submit]" }] };
test("a task with steps shows numbered steps, url link, selector code, proven date, source and version", () => {
  const h = directoriesHtml([by["yelp.com"], { ...by["yelp.com"], domain: "thumbtack.com", name: "Thumbtack" }], [], DEFAULT_FILTERS, "thumbtack.com", [TT]);
  assert.match(h, /data-testid="playbooks-thumbtack.com"/);
  const blk = h.match(/data-testid="pb-thumbtack.com-verify"[\s\S]*?<\/ol>/)[0];
  assert.equal((blk.match(/<li>/g) || []).length, 2);
  assert.match(blk, /<ol>/);
  assert.match(blk, /<a href="https:\/\/www\.thumbtack\.com\/pro\/signup\?category_pk=136256193386480124&amp;zipcode=37066"[^>]*>/);
  assert.match(blk, /<code>#email<\/code>/);
  assert.match(blk, /Last proven 2026-11-13/);
  assert.match(blk, /Source: run t_9de1c978/);
  assert.match(blk, /v1/);
  assert.match(blk, /Send is the signup/);
  assert.ok(!/Stale/.test(blk));
});
test("a missing task says No playbook yet, and all five task blocks render in order", () => {
  const h = playbooksHtml("thumbtack.com", [TT]);
  const order = [...h.matchAll(/data-testid="pb-thumbtack.com-(\w+)"/g)].map((m) => m[1]);
  assert.deepEqual(order, ["check", "create", "claim", "fix", "verify"]);
  assert.deepEqual(PLAYBOOK_TASKS.map((t) => t[0]), order);
  assert.equal((h.match(/No playbook yet/g) || []).length, 4);
  assert.match(h, /Check for a listing/);
  assert.match(playbooksHtml("x.test", []), /No playbook yet/);
  assert.equal((playbooksHtml("x.test", undefined).match(/No playbook yet/g) || []).length, 5);
  // another Directory's row never shows here
  assert.equal((playbooksHtml("yelp.com", [TT]).match(/No playbook yet/g) || []).length, 5);
});
test("step text, selector, source and url are escaped; a javascript: url is no link; a stale row is flagged and says never proven", () => {
  const evil = { domain: "x.test", task: "claim", version: 2, stale: true, last_proven_at: null, source: "<b>src</b>",
    steps: [{ text: "<script>alert(1)</script> & \"q\"", url: "javascript:alert(2)", selector: "<img src=x onerror=3>" }, { text: "ok", url: "https://a.example/?a=1&b=<x>" }] };
  const h = playbooksHtml("x.test", [evil]);
  assert.ok(!h.includes("<script>") && !h.includes("<img src=x") && !h.includes("<b>src"));
  assert.ok(!h.includes("javascript:"));
  assert.match(h, /&lt;script&gt;alert\(1\)&lt;\/script&gt; &amp; &quot;q&quot;/);
  assert.match(h, /&lt;img src=x onerror=3&gt;/);
  assert.match(h, /href="https:\/\/a\.example\/\?a=1&amp;b=&lt;x&gt;"/);
  assert.match(h, /data-testid="pb-stale-x.test-claim"/);
  assert.match(h, /Never proven by a run/);
  assert.ok(!/Last proven/.test(h));
});
test("Directories render without playbook data (table not applied yet)", () => {
  const h = directoriesHtml(SEED, [], DEFAULT_FILTERS, "yelp.com");
  assert.equal((h.match(/No playbook yet/g) || []).length, 5);
});
