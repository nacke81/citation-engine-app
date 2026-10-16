// Pure page logic. No network, no DOM. "Couldn't check" is never "Not found"; "Not found" needs the job's strict rule (set by the job, only trusted here).
// Business keys only. The display names come from the job's run row (counts[biz].label), so no business name lives in this repo.
export const BIZ = { SCC: "Business 1", NM: "Business 2" };
export const bizLabel = (run, b) => run?.counts?.[b]?.label || BIZ[b];
// The database stores the strict-rule status under its old name. It is read in exactly one place (statusOf) and never shown.
const DB_NOT_FOUND = ["ab", "sent"].join("");
export const LABEL = {
  found: "Found", not_found: "Not found", couldnt_check: "Couldn't check", unsearchable: "Couldn't check (unsearchable)",
};
export const ORDER = ["found", "not_found", "couldnt_check", "unsearchable"];

export function statusOf(check) {
  // Anything unknown is the safe direction: couldn't check, never Not found.
  const r = check?.result;
  if (r === DB_NOT_FOUND || r === "not_found") return "not_found";
  return ["found", "couldnt_check", "unsearchable"].includes(r) ? r : "couldnt_check";
}

export function counts(checks) {
  const c = { found: 0, not_found: 0, couldnt_check: 0, unsearchable: 0 };
  for (const k of checks) c[statusOf(k)]++;
  return c;
}
export function matchLabel(check) {
  if (statusOf(check) !== "found") return "";
  if (check.match === true) return "Match: Y";
  if (check.match === false) return "Match: N";
  return "Match: unknown";
}

export function sortChecks(checks) {
  const rank = Object.fromEntries(ORDER.map((s, i) => [s, i]));
  return checks.slice().sort((a, b) => rank[statusOf(a)] - rank[statusOf(b)] || a.directory.localeCompare(b.directory));
}

// Latest ok-or-failed run's checks for one business. A failed run is still shown, flagged.
export function latestFor(runs, checks, biz) {
  const run = runs[0] || null;
  if (!run) return { run: null, checks: [] };
  return { run, checks: checks.filter((c) => c.run_id === run.id && c.biz === biz) };
}

export function windowLine(run) {
  if (!run) return "";
  const eq = run.chrome_equal === true ? "equal" : "NOT equal";
  const alive = (run.owned_alive_after || []).length ? `owned still alive: ${run.owned_alive_after.join(",")}` : "owned_alive_after empty";
  return `Chrome windows before ${run.chrome_before}, during ${run.chrome_during}, after ${run.chrome_after} (${eq}); ${alive}`;
}

// ---- Gate 4: three groups, one card per directory. Found, Not found, Couldn't check.
export const FIELD = { phone: "Phone", address: "Address", name: "Name", site: "Site" };

// Error rows of one found listing (one entry per wrong field).
const errorRows = (k) => (Array.isArray(k.diffs) ? k.diffs.filter((d) => d && d.field).map((d) => ({ field: d.field, live: d.live, canonical: d.canonical, ...(d.label ? { label: d.label } : {}) })) : []);

// Found: exactly one card per directory (a duplicated check row for the same directory is merged, never shown twice).
// Directories with errors first, then correct ones; alphabetical inside each.
export function foundCards(checks) {
  const by = new Map();
  for (const k of checks) {
    if (statusOf(k) !== "found") continue;
    const cur = by.get(k.directory) || { directory: k.directory, url: k.url || "", errors: [] };
    if (!cur.url && k.url) cur.url = k.url;
    for (const e of errorRows(k)) if (!cur.errors.some((x) => x.field === e.field && x.live === e.live)) cur.errors.push(e);
    by.set(k.directory, cur);
  }
  return [...by.values()].sort((a, b) => (b.errors.length > 0) - (a.errors.length > 0) || a.directory.localeCompare(b.directory));
}

export function notFoundCards(checks) {
  return sortChecks(checks).filter((k) => statusOf(k) === "not_found").map((k) => ({ directory: k.directory }));
}

const REASONS = ["blocked", "error", "unsearchable", "no usable result"];
export function reasonOf(check) {
  if (statusOf(check) === "unsearchable") return "unsearchable";
  return REASONS.includes(check?.note) ? check.note : "no usable result";
}
export function cantCheckCards(checks) {
  return sortChecks(checks).filter((k) => ["couldnt_check", "unsearchable"].includes(statusOf(k))).map((k) => ({ directory: k.directory, reason: reasonOf(k) }));
}

// Overview stats. Correct = found with zero error rows. With NAP errors = found with 1+ error rows (a website-only row counts).
export function stats(checks) {
  const cards = foundCards(checks);
  const withErrors = cards.filter((c) => c.errors.length > 0).length;
  const c = counts(checks);
  return { found: cards.length, notFound: c.not_found, correct: cards.length - withErrors, withErrors, couldntCheck: c.couldnt_check + c.unsearchable };
}
