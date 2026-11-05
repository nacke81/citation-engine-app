// Weekly progress chart (t_43e88fb7): hand-rolled inline SVG, no library. Pure builders plus one small wiring function.
// Points come from ce_weekly_metrics (site/metrics.js pointsFor). A null value is a gap: the line breaks there, nothing is drawn, nothing is guessed.
import { METRICS } from './metrics.js';

// 12 distinct, colorblind-safe (Okabe-Ito + Tol). First six (check counts) solid, last six (in-flight/result) dashed.
export const COLORS = ['#0072B2', '#D55E00', '#009E73', '#E69F00', '#7B3FA0', '#CC79A7', '#56B4E9', '#882255', '#8A8A00', '#332288', '#8C510A', '#111111'];
export const DASH = '6 3';
export const GAP_NOTE = 'Gaps = not recorded before weekly snapshots began (11/08).';
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const mmdd = (d) => (/^\d{4}-\d\d-\d\d/.test(d || '') ? `${d.slice(5, 7)}/${d.slice(8, 10)}` : '');

// ---- saved choice (per business). Hidden metric keys only; unknown keys and junk are dropped; storage may be blocked.
export const chartKey = (biz) => 'ce-chart:' + biz;
export function loadHidden(storage, biz) {
  try {
    const v = JSON.parse(storage.getItem(chartKey(biz)) || '[]');
    const ok = new Set(METRICS.map((m) => m[0]));
    return Array.isArray(v) ? v.filter((k) => ok.has(k)) : [];
  } catch { return []; }
}
export function saveHidden(storage, biz, hidden) { try { storage.setItem(chartKey(biz), JSON.stringify(hidden)); } catch { /* storage blocked: keep going */ } }
export const toggleHidden = (hidden, key) => (hidden.includes(key) ? hidden.filter((k) => k !== key) : [...hidden, key]);

const niceMax = (n) => { for (const s of [4, 8, 12, 16, 20, 24, 28, 32, 40, 60, 80, 100, 200]) if (n <= s) return s; return Math.ceil(n / 100) * 100; };

// The SVG only. width is the real card width (700 on desktop); height and fonts stay readable down to ~280px.
export function chartSvg(points, hidden = [], width = 700) {
  const W = Math.max(280, Math.min(700, Math.round(width))), H = W < 480 ? 250 : 290;
  const L = 30, R = 24, T = 12, B = 46, iw = W - L - R, ih = H - T - B, n = points.length;
  const max = niceMax(Math.max(1, ...points.flatMap((p) => METRICS.map(([k]) => p.metrics[k]).filter((v) => Number.isInteger(v)))));
  const x = (i) => L + (n === 1 ? iw / 2 : (iw * i) / (n - 1)), y = (v) => T + ih - (ih * v) / max;
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 62))));
  const grid = [0, 1, 2, 3, 4].map((i) => { const v = (max * i) / 4; return `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#e3e5e8"/><text x="${L - 5}" y="${y(v) + 4}" text-anchor="end" class="ax">${Math.round(v)}</text>`; }).join('');
  const xl = points.map((p, i) => (i % every === 0 || i === n - 1 ? `<text x="${x(i)}" y="${H - 28}" text-anchor="middle" class="ax">Wk ${p.week}</text><text x="${x(i)}" y="${H - 14}" text-anchor="middle" class="ax">${esc(mmdd(p.date))}</text>` : '')).join('');
  const lines = METRICS.map(([k, label], mi) => {
    const col = COLORS[mi], dash = mi >= 6 ? ` stroke-dasharray="${DASH}"` : '';
    let d = '', pen = false, dots = '';
    points.forEach((p, i) => {
      const v = p.metrics[k];
      if (!Number.isInteger(v)) { pen = false; return; }          // gap: lift the pen, draw nothing
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)} `; pen = true;
      dots += `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.2" fill="${col}"/><circle class="hit" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="9" fill="transparent" tabindex="0" data-testid="pt-${k}-${p.week}"><title>Wk ${p.week} · ${esc(p.date)} · ${esc(label)}: ${v}</title></circle>`;
    });
    return `<g data-line="${k}" data-testid="line-${k}"${hidden.includes(k) ? ' style="display:none"' : ''}><path d="${d.trim()}" fill="none" stroke="${col}" stroke-width="2"${dash} stroke-linejoin="round"/>${dots}</g>`;
  }).join('');
  return `<svg class="wsvg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Weekly progress, one line per metric" xmlns="http://www.w3.org/2000/svg" style="max-width:100%;height:auto"><style>.ax{font:11px system-ui,sans-serif;fill:#555}</style>${grid}${xl}${lines}</svg>`;
}

export function legendHtml(biz, hidden = []) {
  return `<div class="wlegend" data-testid="chart-legend">${METRICS.map(([k, label], mi) => `<label class="wchip"><input type="checkbox" data-metric="${k}" data-testid="tog-${k}"${hidden.includes(k) ? '' : ' checked'}><svg class="wsw" width="22" height="8" viewBox="0 0 22 8" aria-hidden="true"><line x1="0" x2="22" y1="4" y2="4" stroke="${COLORS[mi]}" stroke-width="2.5"${mi >= 6 ? ` stroke-dasharray="${DASH}"` : ''} data-testid="sw-${k}"/></svg>${esc(label)}</label>`).join('')}</div>`;
}

// live (optional) = what the tiles show now for the same run. If the queue moved since the weekly snapshot, say so instead of letting the two disagree silently.
export function driftNote(points, live, runId) {
  const last = points[points.length - 1];
  if (!last || !live || last.runId !== runId) return '';
  const diff = METRICS.filter(([k]) => Number.isInteger(last.metrics[k]) && last.metrics[k] !== live[k]);
  return diff.length ? `<div class="note" data-testid="chart-drift">Since the Wk ${last.week} snapshot: ${diff.map(([k, l]) => `${esc(l)} ${last.metrics[k]} to ${live[k]}`).join(', ')}.</div>` : '';
}

export function chartHtml(biz, points, hidden = [], opts = {}) {
  const head = '<div class="bhead">Weekly progress</div>';
  if (!points.length) return `<div class="wchart" data-testid="weekly-chart" data-biz="${esc(biz)}">${head}<div class="note" data-testid="chart-empty">No weekly history yet.</div></div>`;
  return `<div class="wchart" data-testid="weekly-chart" data-biz="${esc(biz)}">${head}<div class="wplot">${chartSvg(points, hidden, opts.width || 700)}</div>${gapNoteHtml(points, hidden)}${legendHtml(biz, hidden)}${opts.note || ''}</div>`;
}

// True when any VISIBLE line has a gap (null / non-integer point).
export const hasVisibleGap = (points, hidden = []) => METRICS.some(([k]) => !hidden.includes(k) && points.some((p) => !Number.isInteger(p.metrics[k])));
// Always rendered (so toggling can flip it); display:none when nothing visible has a gap.
export const gapNoteHtml = (points, hidden = []) => `<div class="note wgap" data-testid="chart-gap-note"${hasVisibleGap(points, hidden) ? '' : ' style="display:none"'}>${esc(GAP_NOTE)}</div>`;

// Wire one chart in the page. A checkbox hides or shows its line (the scale stays put) and the choice is saved per business. Re-draws at the real card width.
export function wireChart(root, biz, points, storage) {
  const box = root.querySelector('.wchart[data-biz="' + biz + '"]');
  if (!box) return;
  const hiddenNow = () => [...box.querySelectorAll('input[data-metric]')].filter((i) => !i.checked).map((i) => i.dataset.metric);
  const draw = () => { if (box.isConnected === false) return; const plot = box.querySelector('.wplot'); if (plot) plot.innerHTML = chartSvg(points, hiddenNow(), plot.clientWidth || 700); };
  box.querySelectorAll('input[data-metric]').forEach((i) => i.addEventListener('change', () => {
    const g = box.querySelector(`g[data-line="${i.dataset.metric}"]`);
    if (g) g.style.display = i.checked ? '' : 'none';
    saveHidden(storage, biz, hiddenNow());
    const gn = box.querySelector('.wgap');
    if (gn) gn.style.display = hasVisibleGap(points, hiddenNow()) ? '' : 'none';
  }));
  draw();
  if (typeof window !== 'undefined' && window.addEventListener) window.addEventListener('resize', draw);
}
