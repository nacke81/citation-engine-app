import { BIZ, bizLabel, LABEL, counts, statusOf, matchLabel, sortChecks, latestFor, windowLine } from './logic.js';
import { SUPABASE_URL, SUPABASE_KEY } from './config.js';

const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
const app = document.getElementById('app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '');
let user = null, data = { runs: [], checks: [] };

async function load() {
  const must = ({ data: d, error }) => { if (error) throw error; return d; };
  const [runs, checks] = await Promise.all([
    sb.from('ce_runs').select('*').order('started_at', { ascending: false }).limit(26).then(must),
    sb.from('ce_checks').select('*').order('checked_on', { ascending: false }).limit(200).then(must),
  ]);
  data = { runs, checks };
}

function home() {
  const { run } = latestFor(data.runs, data.checks, 'SCC');
  if (!run) { app.innerHTML = '<div class="card" data-testid="empty"><b>No weekly check has run yet.</b></div>'; return; }
  const when = new Date(run.finished_at || run.started_at).toLocaleString();
  const cards = Object.keys(BIZ).map((b) => {
    const c = counts(latestFor(data.runs, data.checks, b).checks);
    return `<a class="card biz" href="#${b}" data-testid="biz-${b}"><h2>${esc(bizLabel(latestFor(data.runs, data.checks, b).run, b))}</h2>
      <div class="counts"><span><b>${c.found}</b> found</span><span><b>${c.absent}</b> absent</span><span><b>${c.couldnt_check + c.unsearchable}</b> couldn't check</span></div></a>`;
  }).join('');
  app.innerHTML = `<div class="note" data-testid="runline">Last weekly check ${esc(when)} · ${esc(run.status)}</div>${cards}
    <div class="note" data-testid="windows">${esc(windowLine(run))}</div>`;
}

function bizView(b) {
  const { run, checks } = latestFor(data.runs, data.checks, b);
  if (!run || !BIZ[b]) { home(); return; }
  const rows = sortChecks(checks).map((k) => {
    const st = statusOf(k), u = safeUrl(k.url);
    return `<div class="row" data-testid="row-${esc(k.directory)}"><h3>${esc(k.directory)} <span class="chip ${st}">${esc(LABEL[st])}</span></h3>
      ${st === 'found' ? `${u ? `<div><a href="${esc(u)}" rel="noopener noreferrer" target="_blank">${esc(u)}</a></div>` : ''}
        <div class="nap">${esc(k.nap_shown || 'NAP not captured')}</div>
        <div class="meta ${k.match === true ? 'ok' : 'no'}">${esc(matchLabel(k))}${k.note ? ' · ' + esc(k.note) : ''}</div>` : ''}
      ${st === 'absent' ? '<div class="meta">Directory\'s own search worked and showed no listing.</div>' : ''}
      ${st === 'couldnt_check' ? '<div class="meta">Blocked or unreadable this run. Not a finding either way.</div>' : ''}
      ${st === 'unsearchable' ? '<div class="meta">This Directory\'s own search cannot find known listings (Mike-confirmed label).</div>' : ''}</div>`;
  }).join('');
  const c = counts(checks);
  app.innerHTML = `<a class="back" href="#">&larr; Both businesses</a><h2>${esc(bizLabel(run, b))}</h2>
    <div class="counts"><span><b>${c.found}</b> found</span><span><b>${c.absent}</b> absent</span><span><b>${c.couldnt_check}</b> couldn't check</span><span><b>${c.unsearchable}</b> unsearchable</span></div>${rows}`;
}

function route() { if (!user) return; const h = location.hash.slice(1); BIZ[h] ? bizView(h) : home(); window.scrollTo(0, 0); }

function loginView() {
  user = null; data = { runs: [], checks: [] };
  document.getElementById('me').textContent = '';
  app.innerHTML = `<form class="card" id="lf" novalidate><p>Sign in with your email. We'll send a 6-digit code.</p>
    <input id="email" type="email" autocomplete="email" inputmode="email" placeholder="you@example.com">
    <div style="margin-top:10px"><button class="btn" type="submit" style="width:100%">Email me a code</button></div><div class="err" id="lerr"></div></form>`;
  document.getElementById('lf').onsubmit = async (e) => {
    e.preventDefault();
    const email = document.getElementById('email').value.trim().toLowerCase(), err = document.getElementById('lerr');
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { err.textContent = "That email doesn't look right."; return; }
    err.textContent = 'Sending...';
    const { error } = await sb.auth.signInWithOtp({ email, options: { shouldCreateUser: false } });
    if (error) { err.textContent = /signups? not allowed|not found/i.test(error.message) ? "That email isn't set up for this app." : error.message; return; }
    codeView(email);
  };
}
function codeView(email) {
  app.innerHTML = `<form class="card" id="cf" novalidate><p>Code sent to <b>${esc(email)}</b>. Type it here.</p>
    <input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="••••••" style="letter-spacing:.3em;font-size:22px;text-align:center">
    <div style="margin-top:10px"><button class="btn" type="submit" style="width:100%">Sign in</button></div><div class="err" id="cerr"></div>
    <p class="note"><a href="#" id="again">Use a different email</a></p></form>`;
  document.getElementById('again').onclick = (e) => { e.preventDefault(); loginView(); };
  document.getElementById('cf').onsubmit = async (e) => {
    e.preventDefault();
    const token = document.getElementById('code').value.replace(/\D/g, '');
    const { error } = await sb.auth.verifyOtp({ email, token, type: 'email' });
    if (error) document.getElementById('cerr').textContent = "That code didn't work. Check it, or send a new one.";
  };
}
async function enter(session) {
  user = session.user;
  document.getElementById('me').innerHTML = `${esc(user.email)} · <a href="#" id="signout">Sign out</a>`;
  document.getElementById('signout').onclick = async (e) => { e.preventDefault(); await sb.auth.signOut(); };
  app.innerHTML = '<div class="note">Loading...</div>';
  try { await load(); } catch (e) { app.innerHTML = `<div class="card err">Couldn't load results: ${esc(e.message)}</div>`; return; }
  document.body.dataset.loaded = '1'; route();
}
window.addEventListener('hashchange', route);
let current;
sb.auth.onAuthStateChange((event, session) => {
  const id = session?.user?.id || null;
  if (id === current) return;
  current = id;
  setTimeout(() => (session ? enter(session) : loginView()), 0);
});
window.__ce_codeView = codeView; // test hook, same as Broker Watch
