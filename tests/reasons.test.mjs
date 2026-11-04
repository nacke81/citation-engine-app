// t_93ae9b6b: reason badges, tested on the real 61 rows (trimmed read-only prod pull of run 8f78f625, 2026-11-01).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { builderRows } from "../site/builder.js";
import { cantCheckCards } from "../site/logic.js";
import { bizHtml, esc } from "../site/render.js";
import { reasonFor, codeFromCheckNote, REASONS, reasonFilterHtml } from "../site/reasons.js";

const F = JSON.parse(readFileSync(new URL("./fixtures/reason_rows_61.json", import.meta.url), "utf8"));
const RUN = "8f78f625";
const checks = F.checks.map((c) => ({ ...c, run_id: RUN }));
const runs = [{ id: RUN, status: "ok", started_at: "2026-11-01T11:00:00Z", counts: { SCC: { label: "Business 1" }, NM: { label: "Business 2" } } }];
const dbs = { dirs: F.dirs, dirStatus: F.status };
const forBiz = (b) => ({ cs: checks.filter((c) => c.biz === b), st: F.status.filter((s) => s.biz === b) });

// label per audit row, resolved the way the page does: Needs a person from builderRows, Couldn't check from cantCheckCards
function labelsFor() {
  const out = [];
  for (const biz of ["SCC", "NM"]) {
    const { cs, st } = forBiz(biz);
    for (const r of builderRows(cs, st, F.dirs).filter((x) => x.state === "needsPerson")) out.push({ biz, section: "Needs a person", directory: r.directory, label: r.reason.label, code: r.reason.code });
    for (const c of cantCheckCards(cs, st, F.dirs)) out.push({ biz, section: "Couldn't check", directory: c.directory, label: c.badge.label, code: c.badge.code });
  }
  return out;
}
const L = labelsFor();
const get = (biz, section, d) => L.find((x) => x.biz === biz && x.section === section && x.directory === d);

test("every current SCC + NM row in both sections gets a label, and the sections match the audit counts", () => {
  assert.equal(F.audit.length, 61);
  const c = (b, s) => L.filter((x) => x.biz === b && x.section === s).length;
  assert.deepEqual([c("SCC", "Needs a person"), c("SCC", "Couldn't check"), c("NM", "Needs a person"), c("NM", "Couldn't check")], [28, 13, 6, 14]);
  for (const a of F.audit) assert.ok(get(a.biz, a.section, a.directory), `no label for ${a.biz} ${a.section} ${a.directory}`);
  for (const x of L) assert.ok(REASONS[x.code] && x.label, x.directory);
});

test("fewer than 5% of the 61 rows fall to Other", () => {
  const other = L.filter((x) => x.code === "other");
  assert.ok(other.length / L.length < 0.05, other.map((x) => x.directory).join(","));
  assert.equal(L.length, 61);
});

test("label = count readback (printed for the PR)", () => {
  const n = {};
  for (const x of L) n[x.label] = (n[x.label] || 0) + 1;
  const lines = Object.entries(n).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([k, v]) => `${k} = ${v}`);
  console.log("LABEL_COUNTS\n" + lines.join("\n"));
  assert.equal(Object.values(n).reduce((a, b) => a + b, 0), 61);
  assert.equal(n["Paid listing"], 17); // 2 SCC extra Paid rows in Couldn't check + 1 NM, plus the Needs a person rows, same as the audit
});

test("Nate's two false positives are fixed: cylex is not a wall, usaypage is not CAPTCHA", () => {
  assert.equal(get("SCC", "Needs a person", "cylex.us").label, "Signup form fails");
  assert.equal(get("SCC", "Needs a person", "usaypage.com").label, "Form can't take our NAP");
});

test("Cloudflare is split from the other bot walls", () => {
  assert.equal(get("SCC", "Needs a person", "enrollbusiness.com").label, "Blocked: Cloudflare");
  assert.equal(get("SCC", "Needs a person", "trustpilot.com").label, "Blocked: bot wall");
});

test("the 10 bare 'blocked' rows read 'Blocked (cause unknown)'; data-axle stays in Needs a person with a label", () => {
  const unk = L.filter((x) => x.code === "blocked_unknown");
  assert.equal(unk.length, 10);
  assert.ok(unk.every((x) => x.section === "Couldn't check" && x.label === "Blocked (cause unknown)"));
  assert.equal(get("SCC", "Needs a person", "data-axle.com").label, "Waiting on directory");
});

test("the label never reads gate text: a note that mentions CAPTCHA or Cloudflare changes nothing", () => {
  const dir = { domain: "x.com", cost: "free", dead: false, build_route: "agent" };
  const st = { queue_state: "needs-human", queue_note: "Cloudflare absent. No CAPTCHA solve spent. paid-tier", reason_code: null };
  assert.equal(reasonFor({ status: st, dir, check: { result: "couldnt_check", note: "no usable result" } }).code, "no_result");
  assert.equal(reasonFor({ status: { ...st, reason_code: "nap" }, dir, check: null }).code, "nap");
});

test("an unknown reason_code never throws or shows raw; it falls back to the derived label", () => {
  const r = reasonFor({ status: { reason_code: "made_up" }, dir: { cost: "paid" }, check: null });
  assert.equal(r.code, "paid");
  assert.equal(reasonFor({}).code, "other");
});

test("check notes from job/walls.py map to causes", () => {
  const m = { "blocked: cloudflare": "cloudflare", "blocked: captcha": "captcha", "blocked: bot-wall": "bot_wall", "blocked: http-403": "bot_wall", "blocked: http-429": "bot_wall", "blocked: http-502": "site_down", "blocked: site-down": "site_down", blocked: "blocked_unknown", "blocked: weird": "blocked_unknown", unsearchable: "unsearchable", "no usable result": "no_result" };
  for (const [k, v] of Object.entries(m)) assert.equal(codeFromCheckNote(k), v, k);
  assert.equal(codeFromCheckNote(null), null);
});

test("both sections show the badge next to the name, with the gate text still below it", () => {
  const html = bizHtml(runs, checks, "SCC", dbs, { needsperson: true, cant: true });
  const np = /data-testid="flight-cylex\.us"[\s\S]*?<\/h3>([\s\S]*?)<\/div>\s*<div class="row/.exec(html);
  assert.match(html, /data-testid="flight-cylex\.us"[^>]*><h3>[^<]*<span class="chip rsn rsn-down" data-testid="reason" data-reason="signup_form">Signup form fails<\/span>/);
  assert.match(np[1], /data-testid="note">[^<]*Cloudflare/); // the full gate text stays below, unchanged
  assert.match(html, /data-testid="cant-bizapedia\.com"><h3>bizapedia\.com <span class="chip rsn rsn-wall" data-testid="reason" data-reason="blocked_unknown">Blocked \(cause unknown\)<\/span><\/h3>/);
  assert.match(html, /data-testid="cant-note">blocked</);
});

test("Couldn't check Check line shows the raw ce_checks.note, falling back to the reason", () => {
  const ck = (note) => [{ run_id: RUN, biz: "SCC", directory: "zz.example", result: "couldnt_check", note }];
  const h1 = bizHtml(runs, ck("blocked: http-403"), "SCC", { dirs: [], dirStatus: [] }, { needsperson: true, cant: true });
  assert.match(h1, /data-testid="cant-note">blocked: http-403</);
  const h2 = bizHtml(runs, ck(""), "SCC", { dirs: [], dirStatus: [] }, { needsperson: true, cant: true });
  assert.match(h2, /data-testid="cant-note">no usable result</);
});

test("filter by reason: Paid shows only Paid rows, the section count stays the full group, All restores", () => {
  const all = bizHtml(runs, checks, "SCC", dbs, { needsperson: true });
  const paid = bizHtml(runs, checks, "SCC", dbs, { needsperson: true }, "paid");
  const rows = (h) => ((/<section class="coll" data-sec="needsperson">[\s\S]*?<\/section>/.exec(h) || [""])[0].match(/data-testid="flight-[^"]+"/g) || []).length;
  assert.equal(rows(all), 28);
  assert.equal(rows(paid), 14);
  assert.match(paid, /data-testid="grp-needsperson-n">28</);
  assert.match(paid, /data-testid="rfilt-paid"[^>]*>|aria-pressed="true" data-testid="rfilt-paid"/);
  assert.ok(!/data-testid="flight-cylex\.us"/.test(paid));
  assert.equal(rows(bizHtml(runs, checks, "SCC", dbs, { needsperson: true }, "")), 28);
  assert.match(all, /data-testid="reason-filter"/);
});

test("filter chips escape their text and count every row once", () => {
  const rows = [{ reason: { code: "paid" } }, { reason: { code: "paid" } }, { reason: { code: "captcha" } }];
  const h = reasonFilterHtml(rows, "paid", esc);
  assert.match(h, /All <span class="n">3</);
  assert.match(h, /Paid listing <span class="n">2</);
  assert.match(h, /Blocked: CAPTCHA <span class="n">1</);
  assert.equal(reasonFilterHtml([], "", esc), "");
});

test("backfill file: 61 audit rows -> 58 status rows, only reason_code is set, no insert/delete", () => {
  const bf = JSON.parse(readFileSync(new URL("../db/reason_backfill.json", import.meta.url), "utf8"));
  assert.equal(Object.keys(bf).length, 58);
  for (const v of Object.values(bf)) assert.ok(v.reason_code === null || REASONS[v.reason_code], v.reason_code);
  const sql = readFileSync(new URL("../db/011_reason_code_backfill.sql", import.meta.url), "utf8");
  assert.ok(!/\b(insert|delete|drop|truncate)\b/i.test(sql.replace(/^--.*$/gm, "")));
  const upd = sql.split(/\r?\n/).filter((l) => l.startsWith("update"));
  assert.ok(upd.length > 30 && upd.every((l) => /^update public\.ce_directory_status set reason_code = '[a-z_]+' where biz = '(SCC|NM)' and directory = '[^']+' and reason_code is null;$/.test(l)));
  const mig = readFileSync(new URL("../db/011_reason_code.sql", import.meta.url), "utf8");
  assert.match(mig, /add column if not exists reason_code text;/);
  assert.ok(!/\bnot null\b|\bdefault\b/i.test(mig.split("create or replace view")[0]), "column stays nullable");
  assert.match(mig, /s\.reason_code\s*\nfrom public\.ce_directories/); // the view the app reads exposes it, appended last
});
