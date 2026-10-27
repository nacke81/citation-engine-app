import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { builderRows, builderStats, hasProof, checkedStat } from "../site/builder.js";
import { overviewHtml, bizHtml } from "../site/render.js";

const NF = ["ab", "sent"].join("");
const found = (d, diffs) => ({ biz: "SCC", directory: d, result: "found", diffs: diffs || null, url: "https://" + d + "/x" });
const nf = (d) => ({ biz: "SCC", directory: d, result: NF });
const cc = (d) => ({ biz: "SCC", directory: d, result: "couldnt_check" });
const ERR = [{ field: "phone", live: "111", canonical: "222" }];
const PROOF = { proof_url: "https://a.com/l/1", proof_nap: "Acme 222", proof_at: "2026-10-22T10:00:00Z", proof_nap_match: true };
const st = (d, o) => ({ domain: d, biz: "SCC", ...o });
const stats = (checks, status, dirs) => builderStats(builderRows(checks, status, dirs));

test("G-proof: a submit alone is Waiting, never a result card", () => {
  const s = stats([nf("a.com")], [st("a.com", { queue_state: "submitted", build_action: "new" })]);
  assert.equal(s.waiting, 1); assert.equal(s.newLive + s.claimed + s.fixed, 0);
});
test("G-proof: live without Proof is Waiting", () => {
  const s = stats([nf("a.com")], [st("a.com", { queue_state: "live", build_action: "new" })]);
  assert.equal(s.waiting, 1); assert.equal(s.newLive, 0);
});
test("G-proof: live with Proof whose NAP does not match Canonical is Waiting", () => {
  const s = stats([nf("a.com")], [st("a.com", { queue_state: "live", build_action: "new", ...PROOF, proof_nap_match: false })]);
  assert.equal(s.waiting, 1); assert.equal(s.newLive, 0);
});
test("G-proof: every Proof field is required (url, nap, timestamp, match)", () => {
  for (const k of Object.keys(PROOF)) assert.equal(hasProof({ ...PROOF, [k]: null }), false, k);
  assert.equal(hasProof({ ...PROOF, proof_url: "javascript:alert(1)" }), false);
  assert.equal(hasProof(PROOF), true);
});
test("G-proof: live with full Proof counts in its action's result card", () => {
  assert.equal(stats([nf("a.com")], [st("a.com", { queue_state: "live", build_action: "new", ...PROOF })]).newLive, 1);
  assert.equal(stats([found("b.com")], [st("b.com", { queue_state: "live", build_action: "claim", ...PROOF })]).claimed, 1);
  assert.equal(stats([found("c.com", ERR)], [st("c.com", { queue_state: "live", build_action: "fix", ...PROOF })]).fixed, 1);
});

test("G-queue: queue derives from the finder with no hand entry", () => {
  const checks = [found("fix.com", ERR), nf("new.com"), found("claim.com"), found("owned.com"), cc("unk.com"), found("ownederr.com", ERR)];
  const status = [st("owned.com", { claim_status: "claimed" }), st("ownederr.com", { claim_status: "claimed" })];
  const rows = builderRows(checks, status);
  const by = Object.fromEntries(rows.map((r) => [r.directory, r]));
  assert.equal(by["fix.com"].action, "fix");
  assert.equal(by["new.com"].action, "new");
  assert.equal(by["claim.com"].action, "claim");
  assert.equal(by["owned.com"].state, "none");
  assert.equal(by["ownederr.com"].action, "fix");
  assert.equal(by["unk.com"].state, "none");
  const s = builderStats(rows);
  assert.deepEqual([s.toBuild, s.toBuildNew, s.toBuildClaim, s.toBuildFix], [4, 1, 1, 2]);
});
test("claimed is independent of Correct: correct+unclaimed is a claim candidate, claimed+errors still a fix candidate", () => {
  const unk = builderRows([found("a.com")], [st("a.com", { claim_status: "unknown" })]);
  assert.equal(unk[0].action, "claim");
  assert.equal(builderRows([found("a.com", ERR)], [st("a.com", { claim_status: "claimed" })])[0].action, "fix");
});
test("hard-block cap: a STOPPED row shows in Needs a person with the Mike label", () => {
  const stopped = st("a.com", { queue_state: "needs-human", queue_note: "WALL:hard-block STOPPED, waiting on Mike" });
  const rows = builderRows([nf("a.com")], [stopped]);
  assert.equal(rows[0].state, "needsPerson");
  assert.equal(rows[0].note, "Blocked 3 days, stopped. Mike to look.");
  assert.equal(builderStats(rows).needsPerson, 1);
  const RUN0 = { id: "r", biz: "SCC", status: "ok", finished_at: "2026-10-26T10:00:00Z" };
  assert.match(bizHtml([RUN0], [nf("a.com")], "SCC", { dirs: [], dirStatus: [stopped] }), /Blocked 3 days, stopped\. Mike to look\./);
});
test("hard-block cap: a try 1/3 note is shown as written, not as stopped", () => {
  const r = builderRows([nf("a.com")], [st("a.com", { queue_state: "needs-human", queue_note: "WALL:hard-block try 2/3" })]);
  assert.equal(r[0].note, "WALL:hard-block try 2/3");
});
test("Needs a person: needs-human rows and agent-blocked Directories without a state", () => {
  const s = stats([nf("a.com"), nf("b.com"), nf("c.com")],
    [st("a.com", { queue_state: "needs-human" })], [{ domain: "b.com", agent_access: "blocked" }, { domain: "c.com", agent_access: "ok" }]);
  assert.equal(s.needsPerson, 2); assert.equal(s.toBuildNew, 1);
});
test("one state per row: rejected is in no card, rows never double count", () => {
  const checks = [found("a.com", ERR), nf("b.com")];
  const s = stats(checks, [st("a.com", { queue_state: "rejected" }), st("b.com", { queue_state: "pending-verify" })]);
  assert.equal(s.toBuild + s.waiting + s.needsPerson + s.newLive + s.claimed + s.fixed, 1);
});
test("derive-don't-store: changing a row changes the count", () => {
  const a = stats([nf("a.com")], []).toBuild;
  const b = stats([nf("a.com")], [st("a.com", { queue_state: "submitted" })]).toBuild;
  assert.equal(a, 1); assert.equal(b, 0);
});
test("missing proof columns (old DB) read as no Proof, never over-count", () => {
  const s = stats([nf("a.com")], [st("a.com", { queue_state: "live" })]);
  assert.equal(s.newLive, 0); assert.equal(s.waiting, 1);
});

test("Checked reads 25 of 86", () => {
  const checks = Array.from({ length: 25 }, (_, i) => cc("d" + i + ".com"));
  assert.equal(checkedStat(checks, Array.from({ length: 86 }, (_, i) => ({ domain: "x" + i }))), "25 of 86");
  assert.equal(checkedStat(checks, []), "25");
});

test("overview shows Checked and the six builder cards per business", () => {
  const runs = [{ id: "r1", status: "ok", started_at: "2026-10-18T00:00:00Z", counts: {} }];
  const checks = [{ ...found("a.com", ERR), run_id: "r1" }, { ...nf("b.com"), run_id: "r1" }, { ...cc("c.com"), run_id: "r1" }];
  const html = overviewHtml(runs, checks, { dirs: [{ domain: "a.com" }, { domain: "b.com" }, { domain: "c.com" }], dirStatus: [] });
  for (const id of ["stat-checked", "stat-tobuild", "stat-waiting", "stat-needsperson", "stat-newlive", "stat-claimed", "stat-fixed"]) assert.equal((html.match(new RegExp('data-testid="' + id + '"', "g")) || []).length, 2, id);
  assert.match(html, /3 of 3/); assert.match(html, /1 new · 0 claim · 1 fix/);
  assert.ok(/data-testid="stat-newlive"[^>]*>[\s\S]{0,40}<b[^>]*>0</.test(html));
});
test("overview still renders without the Directory tables (old DB)", () => {
  const runs = [{ id: "r1", status: "ok", started_at: "2026-10-18T00:00:00Z" }];
  assert.ok(overviewHtml(runs, [{ ...found("a.com"), run_id: "r1" }]).includes("stat-checked"));
});

test("390px: stat labels never break mid-word", () => {
  const html = readFileSync(new URL("../site/index.html", import.meta.url), "utf8");
  assert.match(html, /\.stat span[^}]*overflow-wrap:\s*normal/);
  assert.match(html, /\.stat span[^}]*word-break:\s*normal/);
  assert.match(html, /\.biz \.stat[^}]*word-break:\s*normal/);
});
test("migration 003 is additive, nullable, idempotent, no secret", () => {
  const sql = readFileSync(new URL("../db/003_builder_proof.sql", import.meta.url), "utf8");
  assert.ok(!/drop\s+(table|column)|not null|delete\s+from|truncate/i.test(sql.replace(/--.*$/gm, "")));
  for (const c of ["build_action", "proof_url", "proof_nap", "proof_at", "proof_nap_match"]) assert.match(sql, new RegExp("add column if not exists " + c));
  assert.ok(!new RegExp("sb_" + "secret|service" + "_role|e" + "yJ[A-Za-z0-9_-]{30,}").test(sql));
});

test("G-queue: a queued row counts as To build even with no finder candidate; action from queue_kind", () => {
  const s = stats([cc("a.com")], [st("a.com", { queue_state: "queued", queue_kind: "create" }), st("b.com", { queue_state: "queued", queue_kind: "fix" }), st("c.com", { queue_state: "needs-human", queue_kind: "create" })]);
  assert.deepEqual([s.toBuild, s.toBuildNew, s.toBuildFix, s.needsPerson], [2, 1, 1, 1]);
  assert.equal(stats([], [st("d.com", { queue_state: "queued", queue_kind: "create" })]).toBuildNew, 1);
});

// ---- company page (t_eafb85da): page groups come from the same rows as the home cards ----
const RUN = { id: "r1", started_at: "2026-10-26T00:00:00Z", status: "ok", counts: {} };
const mk = () => {
  const checks = [nf("n1.com"), nf("n2.com"), found("c1.com"), found("f1.com", ERR), cc("cc.com"), nf("w1.com"), nf("w2.com"), nf("p1.com"), nf("b1.com"), nf("done.com"), found("claimed.com")].map((c) => ({ ...c, run_id: "r1" }));
  const status = [
    st("n1.com", { queue_state: "queued", build_action: "new" }), st("n2.com", { queue_state: "queued", build_action: "new" }),
    st("w1.com", { queue_state: "submitted", build_action: "new", queue_state_at: "2026-10-25T10:00:00Z" }),
    st("w2.com", { queue_state: "live", build_action: "new", last_url: "https://w2.com/l/1" }),
    st("p1.com", { queue_state: "needs-human", queue_note: "VERIFY:sms", build_action: "new" }),
    st("done.com", { queue_state: "live", build_action: "new", ...PROOF }),
    st("claimed.com", { queue_state: "live", build_action: "claim", ...PROOF }),
  ];
  const dirs = [{ domain: "b1.com", name: "Blocked One", agent_access: "blocked", agent_blocker: "Cloudflare bot wall" }, { domain: "n1.com", name: "Nine One" }];
  return { checks, status, dirs };
};
const count = (h, g) => Number(new RegExp(`data-testid="grp-${g}-n">(\\d+)<`).exec(h)[1]);
const card = (h, id) => Number(new RegExp(`data-testid="${id}"><b[^>]*>(\\d+)<`).exec(h)[1]);
test("company page group totals equal the home card numbers", () => {
  const { checks, status, dirs } = mk(), dbs = { dirs, dirStatus: status };
  const home = overviewHtml([RUN], checks, dbs), page = bizHtml([RUN], checks, "SCC", dbs);
  const pairs = { tobuild: "stat-tobuild", waiting: "stat-waiting", needsperson: "stat-needsperson", newlive: "stat-newlive", claimed: "stat-claimed", fixed: "stat-fixed" };
  for (const [g, id] of Object.entries(pairs)) assert.equal(count(page, g), card(home, id), g);
  assert.deepEqual(Object.keys(pairs).map((g) => count(page, g)), [4, 2, 2, 1, 1, 0]);
});
test("a live row without Proof sits in Waiting labelled Live, proof pending; a gate shows as the reason", () => {
  const { checks, status, dirs } = mk(), page = bizHtml([RUN], checks, "SCC", { dirs, dirStatus: status });
  const w2 = /data-testid="flight-w2.com".*?<\/div>\s*<\/div>/s.exec(page)[0];
  assert.match(w2, /Live, proof pending/); assert.match(w2, /https:\/\/w2.com\/l\/1/);
  assert.match(page, /data-testid="flight-p1.com"[\s\S]*?VERIFY:sms/);
  assert.match(page, /data-testid="flight-b1.com"[\s\S]*?Cloudflare bot wall/); // Directory-level block is the gate
  assert.match(page, /Blocked One/);
  assert.ok(page.indexOf("inflight-title") < page.indexOf("found-title"), "finder section stays below");
  assert.match(page, /data-testid="sub-new"/);
});
test("every home stat card deep-links to its group, and the group exists on the page", () => {
  const { checks, status, dirs } = mk(), dbs = { dirs, dirStatus: status };
  const home = overviewHtml([RUN], checks, dbs), page = bizHtml([RUN], checks, "SCC", dbs);
  const links = [...home.matchAll(/<a class="stat[^"]*" href="#SCC\/(\w+)"/g)].map((m) => m[1]);
  assert.ok(links.length >= 10);
  for (const g of new Set(links)) assert.ok(page.includes(`id="grp-${g}"`), g);
  assert.ok(!/<a[^>]*>[^]*?<a /.test(home.replace(/<\/a>/g, "</a>\n").split("\n").filter((l) => /<a [^]*<a /.test(l)).join("")), "no nested anchors");
});

test("created-unlisted (t_f707b644): exists but not public yet / no full NAP -> Waiting (In flight), never Needs person, never a result card", () => {
  const s = stats([nf("a.com")], [st("a.com", { queue_state: "created-unlisted", queue_note: "page not public yet" })]);
  assert.equal(s.waiting, 1); assert.equal(s.needsPerson, 0); assert.equal(s.newLive + s.claimed + s.fixed, 0);
  const row = builderRows([nf("a.com")], [st("a.com", { queue_state: "created-unlisted" })], [])[0];
  assert.equal(row.state, "waiting"); assert.equal(row.queue, "created-unlisted");
});
