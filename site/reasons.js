// One reason badge per row (t_93ae9b6b). Pure. The label comes from STORED fields only: ce_directory_status.reason_code first, then
// catalog/check columns. Never a regex over gate text (it matched a note that said Cloudflare was gone, and one that said no CAPTCHA was solved).
// tone -> CSS class `rsn-<tone>`.
export const REASONS = {
  paid: { label: 'Paid listing', tone: 'money' },
  captcha: { label: 'Blocked: CAPTCHA', tone: 'wall' },
  cloudflare: { label: 'Blocked: Cloudflare', tone: 'wall' },
  bot_wall: { label: 'Blocked: bot wall', tone: 'wall' },
  blocked_unknown: { label: 'Blocked (cause unknown)', tone: 'wall' },
  site_down: { label: 'Site down', tone: 'down' },
  signup_form: { label: 'Signup form fails', tone: 'down' },
  nap: { label: "Form can't take our NAP", tone: 'down' },
  phone_verify: { label: 'Phone verification (client)', tone: 'client' },
  id_check: { label: 'ID check (client)', tone: 'client' },
  contact_name: { label: 'Contact name required', tone: 'client' },
  login_wall: { label: 'Login wall', tone: 'client' },
  mike_account: { label: "Mike's account only", tone: 'client' },
  declined: { label: 'Declined by Mike', tone: 'quiet' },
  waiting_directory: { label: 'Waiting on directory', tone: 'wait' },
  bad_catalog: { label: 'Bad Catalog row', tone: 'quiet' },
  no_search: { label: 'No search on site', tone: 'quiet' },
  no_result: { label: 'No usable result', tone: 'quiet' },
  unsearchable: { label: 'Unsearchable', tone: 'quiet' },
  other: { label: 'Other: see gate', tone: 'quiet' },
};
export const REASON_CODES = Object.keys(REASONS);

// ce_checks.note written by job/walls.py: "blocked: <kind>" where kind is a wall name or http-NNN. Bare "blocked" = cause not recorded.
export function codeFromCheckNote(note) {
  const n = String(note || '').trim().toLowerCase();
  if (n === 'unsearchable') return 'unsearchable';
  if (n === 'no usable result' || n === 'no-method' || n === 'error') return 'no_result';
  if (n === 'blocked') return 'blocked_unknown';
  const m = /^blocked:\s*(.+)$/.exec(n);
  if (!m) return null;
  const k = m[1];
  if (k === 'cloudflare') return 'cloudflare';
  if (k === 'captcha') return 'captcha';
  if (k === 'bot-wall') return 'bot_wall';
  if (k === 'site-down') return 'site_down';
  const h = /^http-(\d{3})$/.exec(k);
  if (h) return Number(h[1]) >= 500 ? 'site_down' : 'bot_wall'; // 5xx = the site is down; 401/403/429 = a wall that is not named
  return 'blocked_unknown';
}

// -> { code, label, tone }. Sources in order: stored reason_code; catalog flags; the check row. No gate-text matching.
export function reasonFor({ status, dir, check } = {}) {
  let code = null;
  const rc = status && status.reason_code;
  if (rc && REASONS[rc]) code = rc;
  else if (dir && dir.dead) code = /no (business )?search/i.test(dir.dead_reason || '') ? 'no_search' : 'bad_catalog'; // dead_reason is a catalog column, not gate text
  else if (dir && dir.cost === 'paid') code = 'paid';
  else if (dir && dir.build_route === 'agency-account') code = 'mike_account';
  else if (check && check.result === 'unsearchable') code = 'unsearchable';
  else code = codeFromCheckNote(check && check.note);
  if (!code) code = check && check.result === 'couldnt_check' ? 'no_result' : 'other';
  return { code, label: REASONS[code].label, tone: REASONS[code].tone };
}

export const reasonBadge = (r, esc) => `<span class="chip rsn rsn-${esc(r.tone)}" data-testid="reason" data-reason="${esc(r.code)}">${esc(r.label)}</span>`;

// Filter control for "Needs a person": chips with counts, one per code present. `sel` is the chosen code or '' for all.
export function reasonCounts(rows) {
  const m = new Map();
  for (const r of rows) m.set(r.reason.code, (m.get(r.reason.code) || 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([code, n]) => ({ code, n, label: REASONS[code].label }));
}
export function reasonFilterHtml(rows, sel, esc) {
  if (!rows.length) return '';
  const chip = (code, label, n) => `<button type="button" class="btn rfilt${(sel || '') === code ? ' on' : ''}" data-reason-filter="${esc(code)}" aria-pressed="${(sel || '') === code}" data-testid="rfilt-${esc(code || 'all')}">${esc(label)} <span class="n">${n}</span></button>`;
  return `<div class="rfilters" data-testid="reason-filter" role="group" aria-label="Filter by reason">${chip('', 'All', rows.length)}${reasonCounts(rows).map((c) => chip(c.code, c.label, c.n)).join('')}</div>`;
}
