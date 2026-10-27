import { BIZ } from './logic.js';
import { overviewHtml, bizHtml, esc } from './render.js';
import { directoriesHtml, tabsHtml, DEFAULT_FILTERS } from './directories.js';
import { SUPABASE_URL, SUPABASE_KEY } from './config.js';

const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
const app = document.getElementById('app');
let user = null, data = { runs: [], checks: [], dirs: [], dirStatus: [], snapshots: [] };

// client_id -> SCC / NM (the same ids job/portal.py writes); the first row per business is the newest.
const CLIENT_BIZ = { 'e1fb5abd-8d7f-4d83-8cde-18934d149bb5': 'SCC', 'fe3062b5-c956-4358-9e77-840e18be9f85': 'NM' };
const tagSnapshots = (rows) => { const seen = new Set(); return (rows || []).map((r) => ({ ...r, biz: CLIENT_BIZ[r.client_id] })).filter((r) => r.biz && !seen.has(r.biz) && seen.add(r.biz)); };

async function load() {
  const must = ({ data: d, error }) => { if (error) throw error; return d; };
  const [runs, checks] = await Promise.all([
    sb.from('ce_runs').select('*').order('started_at', { ascending: false }).limit(26).then(must),
    sb.from('ce_checks').select('*').order('checked_on', { ascending: false }).limit(200).then(must),
  ]);
  // The Directory database is additive: if the migration is not applied yet, the check pages still load.
  const [dirs, dirStatus] = await Promise.all([
    sb.from('ce_directories').select('*').order('priority').then(must).catch(() => []),
    sb.from('ce_directory_biz').select('*').then(must).catch(() => []),
  ]);
  // Stat cards read the newest footprint_snapshot per client (source citation_engine). Additive: no snapshot access -> the old scan cards show.
  const snapshots = await sb.from('footprint_snapshot').select('client_id,captured_day,payload').eq('source', 'citation_engine').order('captured_day', { ascending: false }).limit(8).then(must).catch(() => []);
  data = { runs, checks, dirs, dirStatus, snapshots: tagSnapshots(snapshots) };
}

function home() { app.innerHTML = tabsHtml('', data.runs) + overviewHtml(data.runs, data.checks, data); }

function bizView(b, target) {
  const h = bizHtml(data.runs, data.checks, b, data);
  if (h === null) { home(); return; }
  app.innerHTML = tabsHtml(b, data.runs) + h;
  // #SCC/<group> scrolls to the group; #SCC/<domain> scrolls to that Directory's row.
  const el = target && (document.getElementById('grp-' + target) || [...app.querySelectorAll('[data-dir]')].find((x) => x.dataset.dir === target));
  if (el) { el.scrollIntoView(); el.classList.add('hl'); } else window.scrollTo(0, 0);
}

// Directories tab: filter, sort and the open row live in memory (the list is 86 rows; no query per tap).
let dirFilters = { ...DEFAULT_FILTERS }, dirOpen = '';
function dirView(keepScroll) {
  const y = window.scrollY;
  app.innerHTML = tabsHtml('directories', data.runs) + directoriesHtml(data.dirs, data.dirStatus, dirFilters, dirOpen);
  app.querySelectorAll('[data-filter]').forEach((el) => {
    el.addEventListener(el.tagName === 'INPUT' ? 'input' : 'change', () => {
      dirFilters = { ...dirFilters, [el.dataset.filter]: el.value };
      dirView(true);
      if (el.tagName === 'INPUT') { const i = app.querySelector('[data-filter="q"]'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
    });
  });
  app.querySelectorAll('[data-open]').forEach((el) => el.addEventListener('click', () => { dirOpen = dirOpen === el.dataset.open ? '' : el.dataset.open; dirView(true); }));
  if (keepScroll) window.scrollTo(0, y);
}

function route() {
  if (!user) return;
  const [h, target] = location.hash.slice(1).split('/');
  if (h === 'directories') dirView(); else if (BIZ[h]) bizView(h, target ? decodeURIComponent(target) : ''); else { home(); window.scrollTo(0, 0); }
}

function loginView() {
  user = null; data = { runs: [], checks: [], dirs: [], dirStatus: [], snapshots: [] };
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
