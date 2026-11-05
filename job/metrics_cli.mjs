// t_43e88fb7: the weekly job's only way to count. Reads a JSON list of jobs on stdin, answers with the page's own functions (site/metrics.js), writes a JSON list on stdout.
//   {mode:"snapshot", checks, status, dirs}                         -> {metrics}            exactly what the tiles show
//   {mode:"rebuild",  checks, queueRows, status, dirs, runDay}     -> {metrics, sources, ranges}   null = cannot be rebuilt (a gap)
// Pure: no network, no file writes.
import { weeklyMetrics, rebuildMetrics } from "../site/metrics.js";

let raw = "";
process.stdin.setEncoding("utf8");
for await (const c of process.stdin) raw += c;
const jobs = JSON.parse(raw || "[]");
const out = jobs.map((j) => {
  if (j.mode === "snapshot") return { metrics: weeklyMetrics(j.checks || [], j.status || [], j.dirs || []) };
  if (j.mode === "rebuild") return rebuildMetrics({ checks: j.checks || [], queueRows: j.queueRows || [], status: j.status || [], dirs: j.dirs || [], runDay: j.runDay });
  throw new Error("unknown mode " + j.mode);
});
process.stdout.write(JSON.stringify(out));
