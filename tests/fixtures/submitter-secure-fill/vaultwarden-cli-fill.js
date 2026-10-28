'use strict';
// Secrets cross process boundaries only through captured stdout, environment or CDP WebSocket.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const SERVER = 'https://bitwardenrs.mikenacke.com';
const TOOLS = 'C:/Users/Mikes Desktop 2023/AppData/Local/hermes/tools';
const BASH = `${TOOLS}/git-2.53.0+3-win32-x64/usr/bin/bash.exe`;
const bwHome = require('./bw-home');
const BW = bwHome.BW;
const BROWSER = `${TOOLS}/agent-browser-0.26.0-win32-x64/bin/agent-browser-win32-x64.exe`;
class SafeError extends Error {}
function requireSafe(ok, code) { if (!ok) throw new SafeError(code); }
function json(text) { try { return JSON.parse(text); } catch { throw new SafeError('invalid-json'); } }
function readCredentials(env) {
  const file = env.BW_ENV_FILE || (env.HERMES_HOME && path.join(env.HERMES_HOME, '.env'));
  requireSafe(file, 'profile-env-unavailable');
  const text = fs.readFileSync(file, 'utf8');
  const values = {};
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*(BW_CLIENTID|BW_CLIENTSECRET|BW_PASSWORD)=(.*)$/);
    if (match) values[match[1]] = match[2];
  }
  requireSafe(['BW_CLIENTID', 'BW_CLIENTSECRET', 'BW_PASSWORD'].every(k => values[k]), 'credentials-unavailable');
  return values;
}
async function withVault(env, action) {
  let privateDir, credentials, childEnv, unlocked = false;
  let failure, result;
  try {
    requireSafe(bwHome.bwPresent(env), 'bw-cli-missing');
    credentials = readCredentials(env);
    privateDir = fs.mkdtempSync(path.join(require('./tmp-dir').realTmpDir(env), 'vw-fill-'));
    childEnv = { ...env, ...credentials, BITWARDENCLI_APPDATA_DIR: privateDir };
    delete childEnv.BW_SESSION;
    const bw = (args, input) => {
      const r = spawnSync(env.BW_GIT_BASH || BASH,
        ['-lc', 'exec "$0" "$@"', env.BW_CLI_SCRIPT || BW, ...args],
        { env: childEnv, input, encoding: 'utf8', windowsHide: true, timeout: 60000, maxBuffer: 16 * 1024 * 1024 });
      requireSafe(!r.error && r.status === 0, 'vault-command-failed');
      return r.stdout;
    };
    requireSafe(bw(['--version']).trim() === '2026.7.0', 'cli-version-mismatch');
    bw(['config', 'server', SERVER]);
    bw(['login', '--apikey']);
    // Mark the attempt first so a failed/partial unlock still goes through lock.
    unlocked = true;
    childEnv.BW_SESSION = bw(['unlock', '--passwordenv', 'BW_PASSWORD', '--raw']).trim();
    requireSafe(childEnv.BW_SESSION, 'empty-session');
    bw(['sync']);
    result = await action(bw);
  } catch (error) { failure = error; }
  finally {
    if (unlocked) {
      try {
        const r = spawnSync(env.BW_GIT_BASH || BASH,
          ['-lc', 'exec "$0" "$@"', env.BW_CLI_SCRIPT || BW, 'lock'],
          { env: childEnv, encoding: 'utf8', windowsHide: true, timeout: 60000 });
        requireSafe(!r.error && r.status === 0, 'vault-lock-failed');
        delete childEnv.BW_SESSION;
        const status = spawnSync(env.BW_GIT_BASH || BASH,
          ['-lc', 'exec "$0" "$@"', env.BW_CLI_SCRIPT || BW, 'status'],
          { env: childEnv, encoding: 'utf8', windowsHide: true, timeout: 60000 });
        requireSafe(!status.error && status.status === 0 && json(status.stdout).status === 'locked', 'vault-lock-unverified');
      } catch { failure = new SafeError('vault-lock-unverified'); }
    }
    if (childEnv) for (const key of ['BW_SESSION', 'BW_PASSWORD', 'BW_CLIENTSECRET', 'BW_CLIENTID']) delete childEnv[key];
    credentials = undefined;
    childEnv = undefined;
    if (privateDir) {
      try { fs.rmSync(privateDir, { recursive: true, force: true }); }
      catch { failure = new SafeError('vault-cache-cleanup-failed'); }
    }
  }
  if (failure) throw failure;
  return result;
}
function unique(entries, predicate, code) {
  const matches = entries.filter(predicate);
  requireSafe(matches.length === 1, code);
  return matches[0];
}
function resolveScope(bw, options) {
  const org = unique(json(bw(['list', 'organizations'])), e => e.name === options.organization, 'organization-not-unique');
  const collection = unique(json(bw(['list', 'collections', '--organizationid', org.id])),
    e => e.name === options.collection && (!e.organizationId || e.organizationId === org.id), 'collection-not-unique');
  return { org, collection };
}
// Registrable domain (eTLD+1) without a public-suffix list: last two labels, three when the TLD is a country code and the second label is a known generic one (co.uk, com.au).
const SECOND_LEVEL = new Set(['co', 'com', 'org', 'net', 'gov', 'edu', 'ac']);
function registrableDomain(host) {
  const h = String(host).toLowerCase().replace(/\.$/, '');
  if (!h || /^[0-9.]+$/.test(h) || h.includes(':') || h.startsWith('[')) return h;   // IP literal: exact host only
  const p = h.split('.');
  if (p.length <= 2) return h;
  const tld = p[p.length - 1], sld = p[p.length - 2];
  return (tld.length === 2 && SECOND_LEVEL.has(sld) ? p.slice(-3) : p.slice(-2)).join('.');
}
function siteKey(u) { const x = new URL(u); return `${x.protocol}//${registrableDomain(x.hostname)}`; }
function readItem(bw, options) {
  const { org, collection } = resolveScope(bw, options);
  // --item-id (t_560dd259): pick by id when two items share a name (item-not-unique). Scope, type and deletion checks still apply.
  const belongs = e => e.type === 1 && e.organizationId === org.id && e.collectionIds?.includes(collection.id) && (options.itemId ? e.id === options.itemId : e.name === options.name) && !e.deletedDate;
  const found = json(bw(['list', 'items', '--organizationid', org.id, '--collectionid', collection.id])).filter(belongs);
  requireSafe(found.length > 0, 'not-found');   // zero matches is not-found, not item-not-unique (t_d7a907d5)
  const item = unique(found, () => true, 'item-not-unique');
  const full = json(bw(['get', 'item', item.id]));
  requireSafe(belongs(full) && full.id === item.id && typeof full.login?.password === 'string' && full.login.password.length > 0, 'invalid-item');
  // t_df278575: match on scheme + registrable domain (accounts.x.com page vs a www.x.com item is fine); a different registrable domain still refuses.
  const pageSite = siteKey(options.url);
  requireSafe(pageSite && full.login.uris?.some(e => { try { return siteKey(e.uri) === pageSite; } catch { return false; } }), 'item-origin-mismatch');
  return full;
}
function browserEndpoint(env, options) {
  requireSafe(/^[a-zA-Z0-9_-]+$/.test(options.session), 'invalid-browser-session');
  // No daemon autostart: require the explicitly selected existing session.
  requireSafe(fs.existsSync(path.join(options.socketDir, `${options.session}.pid`)), 'browser-session-unavailable');
  const browserEnv = {};
  for (const k of ['PATH', 'SystemRoot', 'SYSTEMROOT', 'USERPROFILE', 'HOME', 'TEMP', 'TMP', 'LOCALAPPDATA']) if (env[k]) browserEnv[k] = env[k];
  browserEnv.AGENT_BROWSER_SOCKET_DIR = options.socketDir;
  const r = spawnSync(env.VW_BROWSER_CLI || BROWSER, ['--session', options.session, '--json', 'get', 'cdp-url'],
    { env: browserEnv, encoding: 'utf8', timeout: 15000, windowsHide: true });
  requireSafe(!r.error && r.status === 0, 'browser-endpoint-unavailable');
  const response = json(r.stdout);
  requireSafe(response.success && response.data?.cdpUrl, 'browser-endpoint-unavailable');
  const url = new URL(response.data.cdpUrl);
  requireSafe(url.protocol === 'ws:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname), 'browser-endpoint-not-loopback');
  return url.href;
}
// --cdp http://127.0.0.1:9333: the build Chrome. Ask its /json/version for the browser websocket; loopback only.
async function cdpEndpoint(httpUrl, fetchImpl = fetch) {
  let ws;
  try { const r = await fetchImpl(new URL('/json/version', httpUrl).href); ws = (await r.json()).webSocketDebuggerUrl; } catch { throw new SafeError('browser-endpoint-unavailable'); }
  requireSafe(ws, 'browser-endpoint-unavailable');
  const url = new URL(ws);
  requireSafe(url.protocol === 'ws:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname), 'browser-endpoint-not-loopback');
  return url.href;
}
class Cdp {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.next = 0;
    this.pending = new Map();
    this.socket.addEventListener('message', event => {
      let msg; try { msg = JSON.parse(event.data); } catch { return; }
      const p = this.pending.get(msg.id);
      if (!p) return;
      this.pending.delete(msg.id); clearTimeout(p.timer);
      if (msg.error) p.reject(new SafeError('cdp-command-failed')); else p.resolve(msg.result);
    });
    this.socket.addEventListener('error', () => this.rejectAll());
    this.socket.addEventListener('close', () => this.rejectAll());
  }
  rejectAll() {
    for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(new SafeError('cdp-disconnected')); }
    this.pending.clear();
  }
  async open() {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new SafeError('cdp-connect-timeout')), 10000);
      this.socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      this.socket.addEventListener('error', () => { clearTimeout(timer); reject(new SafeError('cdp-connect-failed')); }, { once: true });
    });
  }
  call(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++this.next;
      const timer = setTimeout(() => { this.pending.delete(id); reject(new SafeError('cdp-command-timeout')); }, 10000);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
  close() { this.rejectAll(); this.socket.close(); }
}
// In-page picker (t_d13bd638): the first VISIBLE match of the selector, so a second hidden/duplicate match (two inputs, a mobile twin) is not fatal.
// If nothing is visible it returns the first match so the caller's own checks still refuse it with the real reason.
const PICK_JS = `const pick = list => { const all = Array.from(list); return all.find(e => e instanceof HTMLInputElement && e.isConnected && e.getClientRects().length && getComputedStyle(e).visibility === 'visible') || all[0]; };`;
// t_f707b644: the selector (default `password`, which is not valid CSS for a field) falls back to the first VISIBLE input[type=password]
// when it matches nothing visible. An explicit --field selector is tried first and wins whenever it matches a visible input.
const PICK_FIELD_JS = `const visibleInput = e => e instanceof HTMLInputElement && e.isConnected && e.getClientRects().length && getComputedStyle(e).visibility === 'visible';
  const pickField = sel => { let list = []; try { list = Array.from(document.querySelectorAll(sel)); } catch { list = []; }
    const hit = list.find(visibleInput); if (hit) return hit;
    const pw = Array.from(document.querySelectorAll('input[type=password]')); return pw.find(visibleInput) || list[0] || pw[0]; };`;
// Page match ignores the #fragment (t_560dd259): an ad adds `#google_vignette` to the URL, and that must not make the page "a different page".
// Scheme, host, path and query still have to match exactly.
function stripFragment(u) { const i = String(u).indexOf('#'); return i < 0 ? String(u) : String(u).slice(0, i); }
// t_df278575: the page match also ignores the ?query (claim flows add tokens/ids). Scheme, host and path still have to match exactly.
function pageKey(u) { return stripFragment(u).split('?')[0]; }
function samePageJs(options) { return `const samePage = h => String(h).split('#')[0].split('?')[0] === ${JSON.stringify(pageKey(options.url))};`; }
function fillExpression(options, password) {
  return `(() => { try {
    ${samePageJs(options)}
    if (!samePage(location.href)) return false;
    ${PICK_JS}
    ${PICK_FIELD_JS}
    const el = pickField(${JSON.stringify(options.field)});
    if (!el) return false;
    if (!(el instanceof HTMLInputElement) || el.type !== 'password' || el.disabled || el.readOnly || !el.getClientRects().length) return false;
    const value = ${JSON.stringify(password)};
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles:true}));
    el.dispatchEvent(new Event('change', {bubbles:true}));
    return samePage(location.href) && el.value === value;
  } catch { return false; } })()`;
}
// Readiness checks carry no credential. Never bypass visibility for a headless DOM.
function readinessExpression(options) {
  return `(() => { try {
    ${samePageJs(options)}
    if (!samePage(location.href)) return 'refused';
    ${PICK_JS}
    ${PICK_FIELD_JS}
    const el = pickField(${JSON.stringify(options.field)});
    if (!el) return 'waiting';
    if (!(el instanceof HTMLInputElement) || el.type !== 'password' || el.disabled || el.readOnly) return 'refused';
    const style = getComputedStyle(el);
    return el.isConnected && el.getClientRects().length && style.visibility === 'visible' ? 'ready' : 'waiting';
  } catch { return 'refused'; } })()`;
}
async function waitForField(cdp, options, sessionId, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const result = await cdp.call('Runtime.evaluate', { expression: readinessExpression(options), returnByValue: true }, sessionId);
    requireSafe(!result.exceptionDetails, 'browser-fill-refused');
    if (result.result?.value === 'ready') return;
    requireSafe(result.result?.value === 'waiting', 'browser-fill-refused');
    if (Date.now() >= deadline) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  } while (Date.now() <= deadline);
  throw new SafeError('browser-field-not-rendered');
}
function retainedExpression(options, password) {
  return `(() => { try {
    ${samePageJs(options)}
    if (!samePage(location.href)) return false;
    ${PICK_JS}
    ${PICK_FIELD_JS}
    const el = pickField(${JSON.stringify(options.field)});
    if (!el) return false;
    return el instanceof HTMLInputElement && el.type === 'password' && !el.disabled && !el.readOnly &&
      el.isConnected && !!el.getClientRects().length && getComputedStyle(el).visibility === 'visible' &&
      el.value === ${JSON.stringify(password)};
  } catch { return false; } })()`;
}
// Several tabs on the same URL (a leftover signup tab, a second window): use the focused one, else the first visible one, else the first.
// A single match is used as-is with no probe. Only a boolean leaves the page; nothing else is read from a non-chosen tab.
async function pickFocusedTarget(cdp, matches) {
  const attach = async t => ({ target: t, sessionId: (await cdp.call('Target.attachToTarget', { targetId: t.targetId, flatten: true })).sessionId });
  if (matches.length === 1) return attach(matches[0]);
  const probed = [];
  for (const t of matches) {
    const a = await attach(t);
    const r = await cdp.call('Runtime.evaluate', { expression: "({ focus: document.hasFocus(), visible: document.visibilityState === 'visible' })", returnByValue: true }, a.sessionId);
    probed.push({ ...a, focus: !r.exceptionDetails && r.result?.value?.focus === true, visible: !r.exceptionDetails && r.result?.value?.visible === true });
  }
  const chosen = probed.find(p => p.focus) || probed.find(p => p.visible) || probed[0];
  return { target: chosen.target, sessionId: chosen.sessionId };
}
async function fillPassword(endpoint, options, password) {
  const cdp = new Cdp(endpoint);
  try {
    await cdp.open();
    const { targetInfos } = await cdp.call('Target.getTargets');
    const matches = targetInfos.filter(t => t.type === 'page' && pageKey(t.url) === pageKey(options.url));
    requireSafe(matches.length >= 1, 'browser-page-not-found');
    const { target, sessionId } = await pickFocusedTarget(cdp, matches);
    await waitForField(cdp, options, sessionId);
    const result = await cdp.call('Runtime.evaluate', { expression: fillExpression(options, password), returnByValue: true }, sessionId);
    requireSafe(!result.exceptionDetails && result.result?.value === true, 'browser-fill-refused');
    // A framework may restore its controlled state on the next render.
    await new Promise(resolve => setTimeout(resolve, 100));
    const retained = await cdp.call('Runtime.evaluate', { expression: retainedExpression(options, password), returnByValue: true }, sessionId);
    requireSafe(!retained.exceptionDetails && retained.result?.value === true, 'browser-fill-not-retained');
  } finally { cdp.close(); }
}
function parseOptions(args) {
  const lookupOnly = args.includes('--lookup-only');
  if (lookupOnly) args = args.filter(a => a !== '--lookup-only');
  const keys = { '--organization': 'organization', '--collection': 'collection', '--name': 'name', '--field': 'field', '--url': 'url', '--browser-session': 'session', '--browser-socket-dir': 'socketDir', '--item-id': 'itemId', '--cdp': 'cdp' };
  const options = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = keys[args[i]], value = args[i + 1];
    requireSafe(key && !options[key] && value && !value.startsWith('--') && !/[\r\n\x00-\x1f]/.test(value), 'invalid-options');
    options[key] = value;
  }
  // --item-id replaces --name as the selector; --cdp (build Chrome, e.g. http://127.0.0.1:9333) replaces the agent-browser session pair.
  if (options.itemId) requireSafe(/^[0-9a-fA-F-]{8,64}$/.test(options.itemId), 'invalid-options');
  if (options.cdp) { const c = new URL(options.cdp); requireSafe(c.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(c.hostname), 'browser-endpoint-not-loopback'); }
  const needed = ['organization', 'collection', 'url', ...(options.itemId ? [] : ['name']), ...(lookupOnly ? [] : [...(options.cdp ? [] : ['session', 'socketDir'])])];
  requireSafe(needed.every(k => options[k]), 'missing-options');
  options.field = options.field || 'password';   // t_f707b644: optional; the in-page fallback finds the first visible password input
  options.name = options.name || `(id ${options.itemId})`;
  options.lookupOnly = lookupOnly;
  const url = new URL(options.url);
  requireSafe(url.href === options.url && !url.username && !url.password && (url.protocol === 'https:' || (url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))), 'unsafe-page-url');
  return options;
}
async function run(options, env = process.env) {
  if (options.lookupOnly) {
    // Exact-match lookup only: no browser, no password leaves the vault session.
    await withVault(env, async bw => { const item = readItem(bw, options); item.login.password = undefined; });
    return `lookup=success matches=1 item=${options.name}`;
  }
  const endpoint = options.cdp ? await cdpEndpoint(options.cdp) : browserEndpoint(env, options);
  await withVault(env, async bw => {
    let item = readItem(bw, options);
    try { await fillPassword(endpoint, options, item.login.password); }
    finally { item.login.password = undefined; item = undefined; }
  });
  return `fill=success field=${options.field} item=${options.name}`;
}
if (require.main === module) {
  (async () => {
    try { console.log(await run(parseOptions(process.argv.slice(2)))); }
    catch (error) { console.error(`fill=failed reason=${error instanceof SafeError ? error.message : 'operation-failed'}`); process.exitCode = 1; }
  })();
}
module.exports = { stripFragment, pageKey, registrableDomain, siteKey, cdpEndpoint, pickFocusedTarget, PICK_JS, run, withVault, resolveScope, readItem, browserEndpoint, Cdp, fillPassword, fillExpression, readinessExpression, waitForField, retainedExpression, parseOptions, SafeError };
