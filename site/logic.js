// Pure page logic. No network, no DOM. "Couldn't check" is never "absent"; "absent" needs the job's strict rule (set by the job, only trusted here).
// Business keys only. The display names come from the job's run row (counts[biz].label), so no business name lives in this repo.
export const BIZ = { SCC: "Business 1", NM: "Business 2" };
export const bizLabel = (run, b) => run?.counts?.[b]?.label || BIZ[b];
export const LABEL = {
  found: "Found", absent: "Absent", couldnt_check: "Couldn't check", unsearchable: "Couldn't check (unsearchable)",
};
export const ORDER = ["found", "absent", "couldnt_check", "unsearchable"];

export function statusOf(check) {
  // Anything unknown is the safe direction: couldn't check, never absent.
  return ORDER.includes(check?.result) ? check.result : "couldnt_check";
}

export function counts(checks) {
  const c = { found: 0, absent: 0, couldnt_check: 0, unsearchable: 0 };
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
