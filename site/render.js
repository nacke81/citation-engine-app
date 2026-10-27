// Pure HTML for the overview and business pages. No DOM, no network: tests import this and check the real markup.
import { builderRows, builderStats, checkedStat } from './builder.js';
import { BIZ, bizLabel, LABEL, statusOf, latestFor, FIELD, foundCards, notFoundCards, cantCheckCards, stats, matchLabel, snapshotSummary, snapshotCardsHtml } from './logic.js';

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '');

export function overviewHtml(runs, checks, dbs = {}) {
  const { run } = latestFor(runs, checks, 'SCC');
  if (!run) return '<div class="card" data-testid="empty"><b>No weekly check has run yet.</b></div>';
  const when = new Date(run.finished_at || run.started_at).toLocaleString();
  const cards = Object.keys(BIZ).map((b) => {
    const l = latestFor(runs, checks, b), s = stats(l.checks);
    const t = builderStats(builderRows(l.checks, (dbs.dirStatus || []).filter((r) => r.biz === b), dbs.dirs));
    const sum = snapshotSummary(dbs.snapshots, b);
    const L = (g, id, inner, cls = 'stat') => `<a class="${cls}" href="#${b}/${g}" data-testid="${id}">${inner}</a>`;
    return `<div class="card biz" data-testid="biz-${b}"><a class="bizlink" href="#${b}"><h2>${esc(bizLabel(l.run, b))}</h2></a>
      ${sum ? snapshotCardsHtml(sum, b) : `<div class="stats">
        ${L('found', 'stat-found', `<b>${s.found}</b><span>Found</span>`, 'stat')}
        ${L('notfound', 'stat-notfound', `<b>${s.notFound}</b><span>Not found</span>`, 'stat')}
        ${L('found', 'stat-correct', `<b class="ok">${s.correct}</b><span class="ok">Correct</span>`, 'stat good')}
        ${L('found', 'stat-errors', `<b class="no">${s.withErrors}</b><span class="no">With NAP errors</span>`, 'stat bad')}
        ${L('cant', 'stat-cant', `<b>${s.couldntCheck}</b><span>Couldn't check</span>`, 'stat')}
        <div class="stat" data-testid="stat-checked"><b>${esc(checkedStat(l.checks, dbs.dirs))}</b><span>Checked</span></div>
      </div>`}
      <div class="bhead">In flight</div>
      <div class="stats">
        ${L('tobuild', 'stat-tobuild', `<b>${t.toBuild}</b><span>To build</span><small>${t.toBuildNew} new · ${t.toBuildClaim} claim · ${t.toBuildFix} fix</small>`, 'stat')}
        ${L('waiting', 'stat-waiting', `<b>${t.waiting}</b><span>Waiting on directory</span>`, 'stat')}
        ${L('needsperson', 'stat-needsperson', `<b>${t.needsPerson}</b><span>Needs a person</span>`, 'stat')}
      </div>
      <div class="bhead">Results</div>
      <div class="stats">
        ${L('newlive', 'stat-newlive', `<b class="ok">${t.newLive}</b><span class="ok">New listings live</span>`, 'stat good')}
        ${L('claimed', 'stat-claimed', `<b class="ok">${t.claimed}</b><span class="ok">Claimed</span>`, 'stat good')}
        ${L('fixed', 'stat-fixed', `<b class="ok">${t.fixed}</b><span class="ok">Fixed</span>`, 'stat good')}
      </div></div>`;
  }).join('');
  return `<div class="note" data-testid="runline">Last weekly check ${esc(when)} · ${esc(run.status)}</div>${cards}`;
}

function errorRow(directory, f) {
  return `<div class="errrow" data-testid="fix-${esc(directory)}-${esc(f.field)}"><div class="fh"><span class="chip stale">${esc(FIELD[f.field] || f.field)}</span>${f.label ? ` <span class="chip lbl" data-testid="fix-label">${esc(f.label)}</span>` : ''}</div>
      <div class="kv"><span>Live</span><b class="no">${esc(f.live)}</b></div>
      <div class="kv"><span>Canonical</span><b class="ok">${esc(f.canonical)}</b></div></div>`;
}

function foundCard(c) {
  const u = safeUrl(c.url);
  const link = u ? `<div class="meta"><a href="${esc(u)}" rel="noopener noreferrer" target="_blank">${esc(u)}</a></div>` : '<div class="meta">No listing URL captured.</div>';
  const body = c.errors.length ? c.errors.map((f) => errorRow(c.directory, f)).join('') : '<div class="kv"><b class="ok" data-testid="correct">correct</b></div>';
  return `<div class="row found-card ${c.errors.length ? 'has-errors' : 'is-correct'}" data-testid="found-${esc(c.directory)}"><h3>${esc(c.directory)} <span class="chip found">${esc(LABEL.found)}</span></h3>${body}${link}</div>`;
}

const fmtAction = (a) => ({ new: 'New', claim: 'Claim', fix: 'Fix' }[a] || '');
function flightRow(r) {
  const l = r.link ? `<a href="${esc(r.link)}" rel="noopener noreferrer" target="_blank">${esc(r.link)}</a>` : '';
  return `<div class="row flight" id="dir-${esc(r.directory)}" data-dir="${esc(r.directory)}" data-testid="flight-${esc(r.directory)}"><h3>${esc(r.name)} ${r.action ? `<span class="chip act" data-testid="action">${esc(fmtAction(r.action))}</span> ` : ''}<span class="chip q-${esc(r.queue || 'queued')}${r.proofPending ? ' q-proof' : ''}" data-testid="queue">${esc(r.queueLabel || '')}</span></h3>
    ${r.note ? `<div class="kv"><span>${r.state === 'needsPerson' ? 'Gate' : 'Note'}</span><b data-testid="note">${esc(r.note)}</b></div>` : ''}
    ${l ? `<div class="kv"><span>${r.state === 'result' ? 'Listing' : 'Link'}</span><b>${l}</b></div>` : ''}
    ${r.changed ? `<div class="kv"><span>Last change</span><b>${esc(r.changed)}</b></div>` : ''}</div>`;
}
// Groups: id is the deep-link target (#SCC/<id>). Members and counts come from builderRows, the same rows the home cards count.
export const GROUPS = [
  ['tobuild', 'To build', (r) => r.state === 'toBuild'], ['waiting', 'Waiting on directory', (r) => r.state === 'waiting'], ['needsperson', 'Needs a person', (r) => r.state === 'needsPerson'],
  ['newlive', 'New listings live', (r) => r.state === 'result' && r.action === 'new'], ['claimed', 'Claimed', (r) => r.state === 'result' && r.action === 'claim'], ['fixed', 'Fixed', (r) => r.state === 'result' && r.action === 'fix'],
];
function groupHtml([id, title, pick], rows) {
  const m = rows.filter(pick), none = '<div class="note">None.</div>';
  let body = m.length ? m.map(flightRow).join('') : none;
  if (id === 'tobuild' && m.length) body = ['new', 'claim', 'fix'].map((a) => { const x = m.filter((r) => r.action === a); return x.length ? `<div class="bhead" data-testid="sub-${a}">${fmtAction(a)} <span class="n">${x.length}</span></div>${x.map(flightRow).join('')}` : ''; }).join('') + m.filter((r) => !['new', 'claim', 'fix'].includes(r.action)).map(flightRow).join('');
  return `<h3 class="sec grp" id="grp-${id}" data-testid="grp-${id}">${esc(title)} <span class="n" data-testid="grp-${id}-n">${m.length}</span></h3>${body}`;
}

export function bizHtml(runs, checks, b, dbs = {}) {
  const { run, checks: cs } = latestFor(runs, checks, b);
  if (!run || !BIZ[b]) return null;
  const found = foundCards(cs), nf = notFoundCards(cs), cc = cantCheckCards(cs);
  const rows = builderRows(cs, (dbs.dirStatus || []).filter((r) => r.biz === b), dbs.dirs);
  const none = (id) => `<div class="note" data-testid="${id}">None.</div>`;
  return `<a class="back" href="#">&larr; Both businesses</a><h2>${esc(bizLabel(run, b))}</h2>
    <h2 class="sec" data-testid="inflight-title">In flight</h2>${GROUPS.slice(0, 3).map((g) => groupHtml(g, rows)).join('')}
    <h2 class="sec" data-testid="results-title">Results</h2>${GROUPS.slice(3).map((g) => groupHtml(g, rows)).join('')}
    <h2 class="sec" id="grp-found" data-testid="found-title">Found <span class="n">${found.length}</span></h2>${found.length ? found.map(foundCard).join('') : none('found-empty')}
    <h2 class="sec" id="grp-notfound" data-testid="notfound-title">Not found <span class="n">${nf.length}</span></h2>${nf.length ? nf.map((x) => `<div class="row" data-testid="notfound-${esc(x.directory)}"><h3>${esc(x.directory)} <span class="chip not_found">${esc(LABEL.not_found)}</span></h3></div>`).join('') : none('notfound-empty')}
    <h2 class="sec" id="grp-cant" data-testid="cant-title">Couldn't check <span class="n">${cc.length}</span></h2>${cc.length ? cc.map((x) => `<div class="row" data-testid="cant-${esc(x.directory)}"><h3>${esc(x.directory)} <span class="chip couldnt_check">${esc(x.reason)}</span></h3></div>`).join('') : none('cant-empty')}`;
}
