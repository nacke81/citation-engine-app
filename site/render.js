// Pure HTML for the overview and business pages. No DOM, no network: tests import this and check the real markup.
import { BIZ, bizLabel, LABEL, statusOf, latestFor, windowLine, FIELD, foundCards, notFoundCards, cantCheckCards, stats, matchLabel } from './logic.js';

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '');

export function overviewHtml(runs, checks) {
  const { run } = latestFor(runs, checks, 'SCC');
  if (!run) return '<div class="card" data-testid="empty"><b>No weekly check has run yet.</b></div>';
  const when = new Date(run.finished_at || run.started_at).toLocaleString();
  const cards = Object.keys(BIZ).map((b) => {
    const l = latestFor(runs, checks, b), s = stats(l.checks);
    return `<a class="card biz" href="#${b}" data-testid="biz-${b}"><h2>${esc(bizLabel(l.run, b))}</h2>
      <div class="stats">
        <div class="stat" data-testid="stat-found"><b>${s.found}</b><span>Found</span></div>
        <div class="stat" data-testid="stat-notfound"><b>${s.notFound}</b><span>Not found</span></div>
        <div class="stat good" data-testid="stat-correct"><b class="ok">${s.correct}</b><span class="ok">Correct</span></div>
        <div class="stat bad" data-testid="stat-errors"><b class="no">${s.withErrors}</b><span class="no">With NAP errors</span></div>
        <div class="stat" data-testid="stat-cant"><b>${s.couldntCheck}</b><span>Couldn't check</span></div>
      </div></a>`;
  }).join('');
  return `<div class="note" data-testid="runline">Last weekly check ${esc(when)} · ${esc(run.status)}</div>${cards}
    <div class="note" data-testid="windows">${esc(windowLine(run))}</div>`;
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

export function bizHtml(runs, checks, b) {
  const { run, checks: cs } = latestFor(runs, checks, b);
  if (!run || !BIZ[b]) return null;
  const found = foundCards(cs), nf = notFoundCards(cs), cc = cantCheckCards(cs);
  const none = (id) => `<div class="note" data-testid="${id}">None.</div>`;
  return `<a class="back" href="#">&larr; Both businesses</a><h2>${esc(bizLabel(run, b))}</h2>
    <h2 class="sec" data-testid="found-title">Found <span class="n">${found.length}</span></h2>${found.length ? found.map(foundCard).join('') : none('found-empty')}
    <h2 class="sec" data-testid="notfound-title">Not found <span class="n">${nf.length}</span></h2>${nf.length ? nf.map((x) => `<div class="row" data-testid="notfound-${esc(x.directory)}"><h3>${esc(x.directory)} <span class="chip not_found">${esc(LABEL.not_found)}</span></h3></div>`).join('') : none('notfound-empty')}
    <h2 class="sec" data-testid="cant-title">Couldn't check <span class="n">${cc.length}</span></h2>${cc.length ? cc.map((x) => `<div class="row" data-testid="cant-${esc(x.directory)}"><h3>${esc(x.directory)} <span class="chip couldnt_check">${esc(x.reason)}</span></h3></div>`).join('') : none('cant-empty')}`;
}
