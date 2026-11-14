// Directories tab: pure logic and HTML. No DOM, no network. Tests import this and check the real markup.
import { BIZ, bizLabel } from './logic.js';
import { esc, safeUrl } from './render.js';

export const ROUTE = { agent: 'Agent', 'agency-account': 'Mike agency account', aggregator: 'Aggregator', none: 'None' };
export const ACCESS = { ok: 'Agent ok', blocked: 'Agent blocked', unknown: 'Access unknown' };
export const COST = { free: 'Free', paid: 'Paid', unknown: 'Cost unknown' };
export const CATEGORY = { general: 'General', aggregator: 'Aggregator', 'niche-senior': 'Senior niche', 'niche-other': 'Other niche', local: 'Local', 'health-senior-care': 'Health / senior care', 'home-services': 'Home services', legal: 'Legal', 'local-regional': 'Local / regional', restaurant: 'Restaurant' };
export const SORTS = { priority: 'Priority', name: 'Name', access: 'Agent access', route: 'Build route', verified: 'Last verified' };
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

const chip = (cls, text) => `<span class="chip ${cls}">${esc(text)}</span>`;

function select(id, label, opts, val) {
  return `<label class="fl"><span>${esc(label)}</span><select data-filter="${id}" data-testid="filter-${id}">${Object.entries(opts).map(([k, v]) => `<option value="${esc(k)}"${k === val ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
}

// Playbooks (t_2cb780c2): the ce_directory_playbooks rows for one Directory, one block per task, in the order we work a site.
export const PLAYBOOK_TASKS = [['check', 'Check for a listing'], ['create', 'Create'], ['claim', 'Claim'], ['fix', 'Fix'], ['verify', 'Verify']];
const day = (t) => (t ? String(t).slice(0, 10) : '');

function stepHtml(s) {
  const u = safeUrl(s && s.url);
  return `<li>${esc(s && s.text)}${u ? ` <a href="${esc(u)}" rel="noopener noreferrer" target="_blank">${esc(u)}</a>` : ''}${s && s.selector ? ` <code>${esc(s.selector)}</code>` : ''}</li>`;
}

export function playbookHtml(domain, task, title, pb) {
  const head = `<h4>${esc(title)}</h4>`;
  if (!pb || !Array.isArray(pb.steps) || !pb.steps.length) return `<div class="pb" data-testid="pb-${esc(domain)}-${task}">${head}<div class="pbnone">No playbook yet</div></div>`;
  const proven = pb.last_proven_at ? 'Last proven ' + esc(day(pb.last_proven_at)) : 'Never proven by a run';
  return `<div class="pb${pb.stale ? ' stale' : ''}" data-testid="pb-${esc(domain)}-${task}">${head}
    <div class="pbmeta"><span data-testid="pb-proven-${esc(domain)}-${task}">${proven}</span>${pb.stale ? ' <span class="chip stale" data-testid="pb-stale-' + esc(domain) + '-' + task + '">Stale: check before trusting</span>' : ''}${pb.source ? ' <span>Source: ' + esc(pb.source) + '</span>' : ''}${pb.version ? ' <span>v' + esc(pb.version) + '</span>' : ''}${pb.send_is_signup ? ' <span>Send is the signup</span>' : ''}</div>
    <ol>${pb.steps.map(stepHtml).join('')}</ol></div>`;
}

export function playbooksHtml(domain, pbs) {
  const by = {};
  for (const p of Array.isArray(pbs) ? pbs : []) if (p && p.domain === domain) by[p.task] = p;
  return `<div class="playbooks" data-testid="playbooks-${esc(domain)}"><h3>Playbooks</h3>${PLAYBOOK_TASKS.map(([t, title]) => playbookHtml(domain, t, title, by[t])).join('')}</div>`;
}

function listRow(d, open, pbs) {
  return `<div class="row dir${open ? ' open' : ''}" data-testid="dir-${esc(d.domain)}"><button type="button" class="dirhead" data-open="${esc(d.domain)}" aria-expanded="${open}">
      <span class="dn">${esc(d.name)}</span><span class="dd">${esc(d.domain)}</span>
      <span class="chips">${chip('rt', ROUTE[d.build_route] || d.build_route)}${chip('ac-' + d.agent_access, ACCESS[d.agent_access] || d.agent_access)}${chip('cs', COST[d.cost] || d.cost)}${d.checked_weekly ? chip('wk', 'Weekly') : ''}</span></button>${open ? detailHtml(d, pbs) : ''}</div>`;
}

const kv = (k, v) => (v === null || v === undefined || v === '' ? '' : `<div class="kv"><span>${esc(k)}</span><b>${v}</b></div>`);
const link = (u) => { const s = safeUrl(u); return s ? `<a href="${esc(s)}" rel="noopener noreferrer" target="_blank">${esc(s)}</a>` : ''; };

export function detailHtml(d, pbs = []) {
  const vm = Array.isArray(d.verification_methods) ? d.verification_methods.join(', ') : '';
  // Client data lives on the company page. This tab links there and shows no status.
  const bizLinks = Object.keys(BIZ).map((b) => `<a class="seescc" data-testid="see-${esc(d.domain)}-${b}" href="#${b}/${esc(d.domain)}">See ${b} status</a>`).join(' ');
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
    <div class="kv"><span>Company pages</span><b>${bizLinks}</b></div>
    ${playbooksHtml(d.domain, pbs)}</div>`;
}

export function directoriesHtml(dirs, _rows, f = DEFAULT_FILTERS, openDomain = '', playbooks = []) {
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
    ${shown.length ? shown.map((d) => listRow(d, d.domain === openDomain, playbooks)).join('') : '<div class="note" data-testid="dirs-none">No Directory matches these filters.</div>'}`;
}

export function tabsHtml(active, runs) {
  const run = runs && runs[0];
  const t = [['', 'Both'], ...Object.keys(BIZ).map((b) => [b, b]), ['directories', 'Directories']];
  return `<nav class="tabs" data-testid="tabs">${t.map(([h, l]) => `<a href="#${h}" class="tab${h === active ? ' on' : ''}" data-testid="tab-${h || 'home'}"${h === active ? ' aria-current="page"' : ''}${h && BIZ[h] ? ` title="${esc(bizLabel(run, h))}"` : ''}>${esc(l)}</a>`).join('')}</nav>`;
}
