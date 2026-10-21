// Directories tab: pure logic and HTML. No DOM, no network. Tests import this and check the real markup.
import { BIZ, bizLabel, LABEL, statusOf } from './logic.js';
import { esc, safeUrl } from './render.js';

export const ROUTE = { agent: 'Agent', 'agency-account': 'Mike agency account', aggregator: 'Aggregator', none: 'None' };
export const ACCESS = { ok: 'Agent ok', blocked: 'Agent blocked', unknown: 'Access unknown' };
export const COST = { free: 'Free', paid: 'Paid', unknown: 'Cost unknown' };
export const CATEGORY = { general: 'General', aggregator: 'Aggregator', 'niche-senior': 'Senior niche', 'niche-other': 'Other niche', local: 'Local' };
export const SORTS = { priority: 'Priority', name: 'Name', access: 'Agent access', route: 'Build route', verified: 'Last verified' };
export const QUEUE_LABEL = { queued: 'Queued', submitted: 'Submitted', 'pending-verify': 'Pending verify', 'needs-human': 'Needs human', live: 'Live', rejected: 'Rejected' };
export const DEFAULT_FILTERS = { route: '', access: '', cost: '', weekly: '', sort: 'priority', q: '' };

const yn = (v) => (v ? 'Yes' : 'No');
const ACCESS_RANK = { blocked: 0, unknown: 1, ok: 2 };

export function filterDirs(dirs, f = DEFAULT_FILTERS) {
  const q = (f.q || '').trim().toLowerCase();
  return dirs.filter((d) =>
    (!f.route || d.build_route === f.route) &&
    (!f.access || d.agent_access === f.access) &&
    (!f.cost || d.cost === f.cost) &&
    (!f.weekly || (f.weekly === 'y') === !!d.checked_weekly) &&
    (!q || d.name.toLowerCase().includes(q) || d.domain.toLowerCase().includes(q)));
}

export function sortDirs(dirs, sort = 'priority') {
  const byName = (a, b) => a.name.localeCompare(b.name);
  const cmp = {
    priority: (a, b) => a.priority - b.priority || (b.da ?? -1) - (a.da ?? -1) || byName(a, b),
    name: byName,
    access: (a, b) => ACCESS_RANK[a.agent_access] - ACCESS_RANK[b.agent_access] || byName(a, b),
    route: (a, b) => String(a.build_route).localeCompare(b.build_route) || byName(a, b),
    verified: (a, b) => String(b.last_verified || '').localeCompare(String(a.last_verified || '')) || byName(a, b),
  }[sort] || byName;
  return dirs.slice().sort(cmp);
}

// Per-business status of one Directory. A listing the agent cannot get to shows as needs-human with its reason.
export function bizStatus(dir, row) {
  const r = row || {};
  let state = r.queue_state || null, reason = r.queue_note || null;
  if (state === 'needs-human' && !reason) reason = dir.agent_blocker || null;
  if ((state === null || state === 'queued') && dir.agent_access === 'blocked') { state = 'needs-human'; reason = dir.agent_blocker || reason; }
  const check = r.last_result ? LABEL[statusOf({ result: r.last_result })] : 'Not checked';
  return { state, reason, check, checkedOn: r.last_checked_on || null, claim: r.claim_status || null, url: safeUrl(r.last_url), match: r.last_match, note: r.last_note || null };
}

export const statusFor = (rows, domain, biz) => (rows || []).find((r) => r.domain === domain && r.biz === biz) || null;

const chip = (cls, text) => `<span class="chip ${cls}">${esc(text)}</span>`;
const stateChip = (s) => (s ? chip('q-' + s, QUEUE_LABEL[s] || s) : '');

function select(id, label, opts, val) {
  return `<label class="fl"><span>${esc(label)}</span><select data-filter="${id}" data-testid="filter-${id}">${Object.entries(opts).map(([k, v]) => `<option value="${esc(k)}"${k === val ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
}

function listRow(d, rows, open) {
  const biz = Object.keys(BIZ).map((b) => { const s = bizStatus(d, statusFor(rows, d.domain, b)); return `<span class="bz" data-testid="row-${esc(d.domain)}-${b}"><b>${b}</b> ${s.state ? stateChip(s.state) : `<span class="muted">${esc(s.check)}</span>`}</span>`; }).join('');
  return `<div class="row dir${open ? ' open' : ''}" data-testid="dir-${esc(d.domain)}"><button type="button" class="dirhead" data-open="${esc(d.domain)}" aria-expanded="${open}">
      <span class="dn">${esc(d.name)}</span><span class="dd">${esc(d.domain)}</span>
      <span class="chips">${chip('rt', ROUTE[d.build_route] || d.build_route)}${chip('ac-' + d.agent_access, ACCESS[d.agent_access] || d.agent_access)}${chip('cs', COST[d.cost] || d.cost)}${d.checked_weekly ? chip('wk', 'Weekly') : ''}</span>
      <span class="bzs">${biz}</span></button>${open ? detailHtml(d, rows) : ''}</div>`;
}

const kv = (k, v) => (v === null || v === undefined || v === '' ? '' : `<div class="kv"><span>${esc(k)}</span><b>${v}</b></div>`);
const link = (u) => { const s = safeUrl(u); return s ? `<a href="${esc(s)}" rel="noopener noreferrer" target="_blank">${esc(s)}</a>` : ''; };

export function detailHtml(d, rows) {
  const vm = Array.isArray(d.verification_methods) ? d.verification_methods.join(', ') : '';
  const bizBlocks = Object.keys(BIZ).map((b) => {
    const s = bizStatus(d, statusFor(rows, d.domain, b));
    return `<div class="bizstat" data-testid="status-${esc(d.domain)}-${b}"><h4>${esc(BIZ[b])} (${b})</h4>
      ${kv('Queue', s.state ? stateChip(s.state) : '<span class="muted">not queued</span>')}
      ${kv('Reason', s.reason ? esc(s.reason) : '')}
      ${kv('Last check', esc(s.check) + (s.checkedOn ? ' on ' + esc(s.checkedOn) : ''))}
      ${kv('Claim', s.claim ? esc(s.claim) : '')}
      ${kv('Listing', link(s.url))}
      ${kv('Check note', s.note ? esc(s.note) : '')}</div>`;
  }).join('');
  return `<div class="detail" data-testid="detail-${esc(d.domain)}">
    ${kv('Category', esc(CATEGORY[d.category] || d.category))}${kv('Priority', esc(d.priority) + (d.da ? ' (DA ' + esc(d.da) + ')' : ''))}
    ${kv('Checked weekly', yn(d.checked_weekly) + ' (' + esc(d.weekly_scope) + ')')}
    ${kv('Search method', esc(d.search_method))}${kv('Search URL', d.search_url_template ? `<code>${esc(d.search_url_template)}</code>` : '')}
    ${kv('Zero-result marker', yn(d.zero_marker_known) + (d.zero_marker_text ? ': ' + esc(d.zero_marker_text) : ''))}
    ${kv('Claim markers', d.claim_markers_verified ? 'Verified. ' + esc(d.claim_markers) : 'Not verified')}
    ${kv('Signup URL', link(d.signup_url))}${kv('Claim URL', link(d.claim_url))}${kv('Help page', link(d.help_url))}
    ${kv('Cost', esc(COST[d.cost] || d.cost) + (d.cost_note ? ': ' + esc(d.cost_note) : ''))}
    ${kv('Account needed', esc(d.account_needed) + (d.account_note ? ': ' + esc(d.account_note) : ''))}
    ${kv('Verification', esc(vm))}
    ${kv('Build route', esc(ROUTE[d.build_route] || d.build_route) + (d.build_route_note ? '. ' + esc(d.build_route_note) : ''))}
    ${kv('Agent access', esc(ACCESS[d.agent_access] || d.agent_access) + (d.agent_blocker ? ': ' + esc(d.agent_blocker) : '') + (d.agent_blocker_seen_on ? ' (last seen ' + esc(d.agent_blocker_seen_on) + ')' : ''))}
    ${kv('Notes', d.notes ? esc(d.notes) : '')}${kv('Last verified', d.last_verified ? esc(d.last_verified) : '')}
    ${bizBlocks}</div>`;
}

export function directoriesHtml(dirs, rows, f = DEFAULT_FILTERS, openDomain = '') {
  if (!dirs || !dirs.length) return '<div class="card" data-testid="dirs-empty"><b>No Directory data yet.</b> Apply db/002_directories.sql.</div>';
  const shown = sortDirs(filterDirs(dirs, f), f.sort);
  const blocked = dirs.filter((d) => d.agent_access === 'blocked').length;
  const controls = `<div class="filters" data-testid="filters">
    <input type="search" data-filter="q" data-testid="filter-q" placeholder="Search name or domain" value="${esc(f.q)}" aria-label="Search Directories">
    ${select('route', 'Build route', { '': 'All routes', ...ROUTE }, f.route)}${select('access', 'Agent access', { '': 'All', ...ACCESS }, f.access)}
    ${select('cost', 'Cost', { '': 'All', ...COST }, f.cost)}${select('weekly', 'Checked weekly', { '': 'All', y: 'Yes', n: 'No' }, f.weekly)}
    ${select('sort', 'Sort by', SORTS, f.sort)}</div>`;
  return `<h2>Directories <span class="n" data-testid="dir-count">${shown.length} of ${dirs.length}</span></h2>
    <div class="note">${blocked} blocked for the agent. Tap a Directory for everything we know.</div>${controls}
    ${shown.length ? shown.map((d) => listRow(d, rows, d.domain === openDomain)).join('') : '<div class="note" data-testid="dirs-none">No Directory matches these filters.</div>'}`;
}

export function tabsHtml(active, runs) {
  const run = runs && runs[0];
  const t = [['', 'Both'], ...Object.keys(BIZ).map((b) => [b, b]), ['directories', 'Directories']];
  return `<nav class="tabs" data-testid="tabs">${t.map(([h, l]) => `<a href="#${h}" class="tab${h === active ? ' on' : ''}" data-testid="tab-${h || 'home'}"${h === active ? ' aria-current="page"' : ''}${h && BIZ[h] ? ` title="${esc(bizLabel(run, h))}"` : ''}>${esc(l)}</a>`).join('')}</nav>`;
}
