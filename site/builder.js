// Builder stats: pure logic, no DOM, no network. Everything is derived from stored rows (finder checks + per-business status); no totals are stored.
// State machine (one state per business x Directory row, first match wins) is documented in plans/2026-10-22-builder-stat-cards.md and the PR.
import { statusOf } from './logic.js';

const hasErrors = (k) => Array.isArray(k.diffs) && k.diffs.some((d) => d && d.field);
const dirOf = (s) => s.domain || s.directory;
const KIND_ACTION = { fix: 'fix', create: 'new' };
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '');
export const QUEUE_LABEL = { queued: 'Queued', submitted: 'Submitted', 'pending-verify': 'Pending verify', 'needs-human': 'Needs human', live: 'Live', rejected: 'Rejected' };

export const STOPPED_LABEL = 'Blocked 3 days, stopped. Mike to look.';

// Done = Proof: live URL + captured NAP + timestamp, and the captured NAP matched Canonical.
export const hasProof = (s) => !!s && /^https?:\/\//i.test(s.proof_url || '') && !!(s.proof_nap || '').trim() && !!s.proof_at && s.proof_nap_match === true;

// Candidate action derived from the finder. Never hand entered.
// found with NAP errors -> fix; found and not owned by us (correct or not) -> claim; not found -> new; couldn't check -> none.
export function candidateAction(check, status) {
  if (!check) return null;
  const s = statusOf(check);
  if (s === 'found') {
    if (hasErrors(check)) return 'fix';
    return status?.claim_status === 'claimed' ? null : 'claim';
  }
  if (s === 'not_found') return 'new';
  return null;
}

// One row per Directory known to this business: checked in the latest run, or carrying a queue state.
export function builderRows(checks, status, dirs) {
  const st = new Map((status || []).map((r) => [dirOf(r), r]));
  const dr = new Map((dirs || []).map((d) => [d.domain, d]));
  const ck = new Map();
  for (const k of checks || []) {
    const cur = ck.get(k.directory);
    // A duplicated check row for one Directory is merged: found beats the rest, errors from any row count.
    if (!cur || (statusOf(k) === 'found' && statusOf(cur) !== 'found')) ck.set(k.directory, k);
    else if (statusOf(k) === 'found' && hasErrors(k) && !hasErrors(cur)) ck.set(k.directory, k);
  }
  const names = new Set([...ck.keys(), ...[...st.values()].filter((r) => r.queue_state).map(dirOf)]);
  return [...names].sort().map((directory) => {
    const check = ck.get(directory) || null, s = st.get(directory) || null, d = dr.get(directory) || null;
    const cand = candidateAction(check, s), q = s?.queue_state || null;
    let state = 'none', action = cand;
    if (q === 'live' && hasProof(s)) { state = 'result'; action = s.build_action || KIND_ACTION[s.queue_kind] || cand; }
    else if (q === 'live' || q === 'submitted' || q === 'pending-verify') state = 'waiting';
    else if (q === 'needs-human' || ((!q || q === 'queued') && d?.agent_access === 'blocked' && (cand || q === 'queued'))) state = 'needsPerson';
    else if (q === 'rejected') state = 'none';
    else if (cand || q === 'queued') state = 'toBuild'; // a queued row is work to do even when the finder had no candidate (never checked, couldn't check)
    if (state === 'waiting' || state === 'needsPerson') action = s?.build_action || cand || KIND_ACTION[s?.queue_kind] || null;
    if (state === 'toBuild' && !action) action = KIND_ACTION[s?.queue_kind] || null;
    // Display fields for the company page. State and action above are the only inputs to the counts.
    const proofPending = q === 'live' && state === 'waiting';
    // A Directory-level block (agent_access blocked) is the gate when the queue row carries no note of its own.
    let note = s?.queue_note || null;
    if (state === 'needsPerson' && !note) note = d?.agent_blocker || null;
    if (state === 'needsPerson' && d?.cost === 'paid' && !/paid/i.test(note || '')) note = [note, 'Paid' + (d.cost_note ? ': ' + d.cost_note : '')].filter(Boolean).join('. ');
    // Hard-block cap (job/walls.py): after the 3rd failed try the row is stopped until Mike looks.
    if (state === 'needsPerson' && /^WALL:hard-block STOPPED/.test(note || '')) note = STOPPED_LABEL;
    const queue = q || (state === 'needsPerson' ? 'needs-human' : state === 'toBuild' ? 'queued' : null);
    const changed = String(s?.queue_state_at || s?.status_updated_at || s?.last_checked_on || '').slice(0, 10) || null;
    return { directory, state, action, name: d?.name || directory, queue, queueLabel: proofPending ? 'Live, proof pending' : (QUEUE_LABEL[queue] || queue), proofPending, note,
      link: safeUrl(s?.proof_url) || safeUrl(s?.last_url) || safeUrl(check?.url) || '', changed };
  });
}

export function builderStats(rows) {
  const n = (state, action) => rows.filter((r) => r.state === state && (!action || r.action === action)).length;
  return {
    toBuild: n('toBuild'), toBuildNew: n('toBuild', 'new'), toBuildClaim: n('toBuild', 'claim'), toBuildFix: n('toBuild', 'fix'),
    waiting: n('waiting'), needsPerson: n('needsPerson'),
    newLive: n('result', 'new'), claimed: n('result', 'claim'), fixed: n('result', 'fix'),
  };
}

// Directories checked in the latest run of one business / Catalog size. "of N" is dropped when the Directory table did not load.
export function checkedStat(checks, dirs) {
  const done = new Set((checks || []).map((k) => k.directory)).size; // a Directory the weekly run visited, whatever the result
  return dirs && dirs.length ? `${done} of ${dirs.length}` : String(done);
}
