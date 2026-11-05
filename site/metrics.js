// Weekly metrics (t_43e88fb7). Pure: no DOM, no network. The 12 numbers are exactly the 12 home tiles, computed by the SAME functions the tiles use
// (stats, builderRows, builderStats, checkedCount). The weekly job reaches this file through job/metrics_cli.mjs, so Python never re-implements a count.
import { builderRows, builderStats, checkedCount, hasProof } from './builder.js';
import { stats } from './logic.js';

// One line per home tile, tile labels, tile order.
export const METRICS = [
  ['found', 'Found'], ['notFound', 'Not found'], ['correct', 'Correct'], ['withErrors', 'With NAP errors'], ['couldntCheck', "Couldn't check"], ['checked', 'Checked'],
  ['toBuild', 'To build'], ['waiting', 'Waiting on directory'], ['needsPerson', 'Needs a person'], ['newLive', 'New listings live'], ['claimed', 'Claimed'], ['fixed', 'Fixed'],
];
export const CHECK_KEYS = ['found', 'notFound', 'correct', 'withErrors', 'couldntCheck', 'checked'];
export const QUEUE_KEYS = ['toBuild', 'waiting', 'needsPerson', 'newLive', 'claimed', 'fixed'];

const checkMetrics = (checks) => {
  const s = stats(checks || []);
  return { found: s.found, notFound: s.notFound, correct: s.correct, withErrors: s.withErrors, couldntCheck: s.couldntCheck, checked: checkedCount(checks) };
};

// What the tiles show for one business right now. The weekly snapshot is exactly this.
export function weeklyMetrics(checks, status, dirs) {
  const t = builderStats(builderRows(checks, status, dirs));
  return { ...checkMetrics(checks), toBuild: t.toBuild, waiting: t.waiting, needsPerson: t.needsPerson, newLive: t.newLive, claimed: t.claimed, fixed: t.fixed };
}

// ---- Rebuild of a past week. A value is filled only when EVERY state the data allows gives the same count; otherwise null (a gap in the line).
const IN_METRIC = {
  toBuild: (r) => r.state === 'toBuild', waiting: (r) => r.state === 'waiting', needsPerson: (r) => r.state === 'needsPerson',
  newLive: (r) => r.state === 'result' && r.action === 'new', claimed: (r) => r.state === 'result' && r.action === 'claim', fixed: (r) => r.state === 'result' && r.action === 'fix',
};
const day = (v) => String(v || '').slice(0, 10);

// Every queue state the row could have had at the start of runDay. History is date-only and append-only:
//  entries before runDay are certain; entries ON runDay may be before or after the run (any prefix); before the first entry the row did not exist yet or was queued.
export function possibleQueueStates(history, runDay, currentState) {
  const h = (history || []).filter((e) => e && e.at);
  if (!h.length) return currentState ? [null, currentState] : [null];
  const before = h.filter((e) => day(e.at) < runDay), same = h.filter((e) => day(e.at) === runDay);
  const out = new Set();
  if (before.length) out.add(before[before.length - 1].to); else out.add(null), out.add(h[0].from || 'queued');
  for (const e of same) out.add(e.to);
  return [...out];
}

// inputs: checks (this run, one business), queueRows (queue file rows, [] when the business has none), status (CURRENT status rows by directory), dirs, runDay (YYYY-MM-DD).
export function rebuildMetrics({ checks, queueRows, status, dirs, runDay }) {
  const metrics = checkMetrics(checks), sources = Object.fromEntries(CHECK_KEYS.map((k) => [k, 'ce_checks'])), ranges = {};
  const stBy = new Map((status || []).map((r) => [r.domain || r.directory, r])), dBy = new Map((dirs || []).map((d) => [d.domain, d]));
  const qBy = new Map((queueRows || []).map((r) => [r.directory, r]));
  const names = new Set([...(checks || []).map((k) => k.directory), ...qBy.keys()]);
  const ckBy = new Map();
  for (const k of checks || []) ckBy.set(k.directory, [...(ckBy.get(k.directory) || []), k]);
  const lo = Object.fromEntries(QUEUE_KEYS.map((k) => [k, 0])), hi = { ...lo };
  for (const directory of names) {
    const q = qBy.get(directory), cur = stBy.get(directory) || null, d = dBy.get(directory) || null;
    const qs = q ? possibleQueueStates(q.history, runDay, q.state) : [null];
    const outcomes = [];
    for (const state of qs) {
      const proofs = state === 'live' && cur && hasProof(cur) ? (day(cur.proof_at) < runDay ? [true] : day(cur.proof_at) === runDay ? [true, false] : [false]) : [false];
      const open = !state || state === 'queued';   // claim_status and agent_access only matter while no queue move has happened
      for (const proof of proofs) for (const claim of open ? ['claimed', 'unknown'] : ['unknown']) for (const access of open ? ['ok', 'blocked'] : ['ok']) {
        const row = { directory, queue_state: state, queue_kind: cur?.queue_kind || (q?.kind ? q.kind : null), build_action: cur?.build_action || null, claim_status: claim, queue_state_at: null };
        if (proof) Object.assign(row, { proof_url: cur.proof_url, proof_nap: cur.proof_nap, proof_at: cur.proof_at, proof_nap_match: cur.proof_nap_match });
        const rows = builderRows(ckBy.get(directory) || [], [row], [{ ...(d || { domain: directory }), domain: directory, agent_access: access }]);
        outcomes.push(rows.find((r) => r.directory === directory) || { state: 'none', action: null });
      }
    }
    for (const key of QUEUE_KEYS) {
      const f = IN_METRIC[key];
      if (outcomes.every(f)) lo[key]++;
      if (outcomes.some(f)) hi[key]++;
    }
  }
  for (const key of QUEUE_KEYS) {
    ranges[key] = [lo[key], hi[key]];
    metrics[key] = lo[key] === hi[key] ? lo[key] : null;
    sources[key] = lo[key] === hi[key] ? 'queue history' : 'gap';
  }
  return { metrics, sources, ranges };
}

// Weekly points for one business from stored snapshot rows (ce_weekly_metrics), oldest first.
export function pointsFor(rows, biz) {
  return (rows || []).filter((r) => r && r.biz === biz && r.metrics && Number.isInteger(r.week_index)).sort((a, b) => a.week_index - b.week_index)
    .map((r) => ({ week: r.week_index, date: day(r.captured_on), metrics: r.metrics, runId: r.run_id }));
}
