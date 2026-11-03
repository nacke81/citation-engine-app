'use strict';
// usage: node readmail.js [N=5] [filter]
// Read-only: prints the last N messages from the listings@ INBOX (EXAMINE + BODY.PEEK, nothing is marked read or changed).
// t_d13bd638: the whole body is fetched (the old 12000-byte partial fetch and 14000-char print cut long HTML mails and lost the verify link).
// Per message: header, then LINKS (extracted from the full body, verify/confirm/activate links first), then the decoded text up to MAX_TEXT chars.
const SK = require('node:path').join(__dirname, 'listings-imap-vault.js');
const tls = require('node:tls');

const MAX_TEXT = 60000;
const VERIFY_RE = /verif|confirm|activate|validate|token|code=|click|signup|register|claim|welcome|password|reset/i;
const NOISE_RE = /unsubscribe|optout|opt-out|preferences|\.(png|jpe?g|gif|svg|css|woff2?)(\?|$)|\/track(ing)?\/open|pixel|facebook\.com\/|twitter\.com\/|linkedin\.com\/|instagram\.com\//i;

const q = s => '"' + s.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';

function fetchCommand(tag, from, to) {
  // No <0.N> partial: the whole BODY[TEXT] is returned.
  return `${tag} FETCH ${from}:${to} (BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT])`;
}

// Parse the untagged FETCH responses. buf is a latin1 string (1 char = 1 byte), so IMAP literal sizes {n} are exact.
function parseFetch(buf) {
  const msgs = [];
  const re = /\* (\d+) FETCH \(/g;
  let m;
  while ((m = re.exec(buf))) {
    const seq = Number(m[1]);
    let i = re.lastIndex;
    const parts = [];
    while (i < buf.length) {
      const sec = /^\s*BODY\[([^\]]*)\](?:<\d+>)?\s+/.exec(buf.slice(i, i + 200));
      if (!sec) break;
      i += sec[0].length;
      const lit = /^\{(\d+)\}\r\n/.exec(buf.slice(i, i + 20));
      if (!lit) {  // NIL or quoted
        const e = buf.indexOf('\r\n', i);
        parts.push({ section: sec[1], data: '' }); i = e < 0 ? buf.length : e; continue;
      }
      i += lit[0].length;
      const n = Number(lit[1]);
      parts.push({ section: sec[1], data: buf.slice(i, i + n), truncated: i + n > buf.length });
      i += n;
    }
    re.lastIndex = Math.max(re.lastIndex, i);
    const header = (parts.find(p => /^HEADER/.test(p.section)) || { data: '' }).data;
    const text = (parts.find(p => p.section === 'TEXT') || { data: '' });
    msgs.push({ seq, header, body: text.data, truncated: !!text.truncated });
  }
  return msgs;
}

function decodeQP(s) {
  return s.replace(/=\r?\n/g, '').replace(/=([0-9A-Fa-f]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
}
const fromLatin1 = s => Buffer.from(s, 'latin1').toString('utf8');

// Split a (possibly multipart) body into decoded text chunks. Handles quoted-printable and base64 parts; plain bodies fall through.
function decodeBody(body) {
  const out = [];
  const bound = /^--([^\r\n]+)\r?\n(?=[A-Za-z-]+:)/m.exec(body);
  const chunks = bound ? body.split(new RegExp('\\r?\\n?--' + bound[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?:--)?\\r?\\n?')) : [body];
  for (const c of chunks) {
    const hm = /^([\s\S]*?)\r?\n\r?\n([\s\S]*)$/.exec(c);
    const head = bound && hm && /^[A-Za-z-]+:/.test(c) ? hm[1] : '';
    const data = bound && hm && head ? hm[2] : c;
    if (head && /content-type:\s*(image|application|audio|video)\//i.test(head)) continue;
    const enc = (/content-transfer-encoding:\s*([\w-]+)/i.exec(head) || [])[1] || '';
    if (/base64/i.test(enc)) out.push(Buffer.from(data.replace(/\s+/g, ''), 'base64').toString('utf8'));
    else if (/quoted-printable/i.test(enc) || (!head && /=\r?\n|=3D/.test(data))   /* t_57178c17: undeclared QP is only trusted on a soft break or =3D; a bare =20 / =AB is a literal query value (activateid=2043..) */) out.push(fromLatin1(decodeQP(data)));
    else out.push(fromLatin1(data));
  }
  return out.join('\n');
}

const decodeEntities = s => s.replace(/&amp;/g, '&').replace(/&#x3d;|&#61;/gi, '=').replace(/&#x2f;|&#47;/gi, '/').replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');

function extractLinks(text) {
  const seen = new Set(); const links = [];
  const add = u => {
    u = decodeEntities(u).replace(/[)>\].,;'"]+$/, '');
    if (!/^https?:\/\/[^\s<>"']{4,}$/i.test(u) || seen.has(u)) return;
    seen.add(u); links.push(u);
  };
  for (const m of text.matchAll(/href\s*=\s*["']([^"']+)["']/gi)) add(m[1]);
  for (const m of text.matchAll(/https?:\/\/[^\s<>"']+/gi)) add(m[0]);
  const rank = u => (VERIFY_RE.test(u) && !NOISE_RE.test(u) ? 0 : NOISE_RE.test(u) ? 2 : 1);
  return links.map((u, i) => ({ u, i })).sort((a, b) => rank(a.u) - rank(b.u) || a.i - b.i).map(x => x.u);
}

function toText(decoded) {
  return decodeEntities(decoded.replace(/<(style|script)[\s\S]*?<\/\1>/gi, ' ').replace(/<br\s*\/?>|<\/(p|div|tr|li|h\d)>/gi, '\n').replace(/<[^>]+>/g, ' '))
    .replace(/[ \t]+/g, ' ').replace(/\n[ \t]+/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}

function formatMessage(msg, maxText = MAX_TEXT) {
  const decoded = decodeBody(msg.body);
  const links = extractLinks(decoded);
  const text = toText(decoded);
  const lines = ['-----', fromLatin1(decodeQP(msg.header)).trim(), `body_chars=${decoded.length}${msg.truncated ? ' (SERVER CUT THE BODY SHORT)' : ''}`, `LINKS (${links.length}):`];
  links.forEach((u, i) => lines.push(`  [${i + 1}] ${u}`));
  lines.push('TEXT:', text.length > maxText ? text.slice(0, maxText) + `\n...[text cut at ${maxText} of ${text.length} chars; every link above was read from the full body]` : text);
  return lines.join('\n');
}

function run({ host, port, user, password }, N, connect = tls.connect) {
  return new Promise(resolve => {
    let buf = '', step = 0, total = 0, out = '';
    const sock = connect({ host, port: Number(port), servername: host });
    sock.setTimeout && sock.setTimeout(60000, () => { sock.destroy(); resolve(buf); });
    const send = s => sock.write(s + '\r\n');
    sock.on('data', d => {
      buf += Buffer.isBuffer(d) ? d.toString('latin1') : String(d);
      if (step === 0 && /\r\n/.test(buf)) { step = 1; buf = ''; send(`a1 LOGIN ${q(user)} ${q(password)}`); return; }
      if (step === 1 && /^a1 (OK|NO|BAD)/m.test(buf)) { step = 2; buf = ''; send('a2 EXAMINE INBOX'); return; }
      if (step === 2 && /^a2 (OK|NO|BAD)/m.test(buf)) {
        const m = buf.match(/\* (\d+) EXISTS/); total = m ? Number(m[1]) : 0; step = 3; buf = '';
        if (!total) { step = 4; send('a4 LOGOUT'); return; }
        send(fetchCommand('a3', Math.max(1, total - N + 1), total)); return;
      }
      if (step === 3 && /\r\na3 (OK|NO|BAD)[^\r\n]*\r\n$/.test(buf)) { out = buf; step = 4; send('a4 LOGOUT'); return; }
      if (step === 4 && /a4 OK|BYE/.test(buf)) { sock.destroy(); resolve(out); }
    });
    sock.on('error', () => resolve('ERR'));
    sock.on('close', () => resolve(out));
  });
}

async function main(argv, withImap = require(SK).withImap, log = console.log) {
  const N = Number(argv[0] || 5);
  const filter = (argv[1] || '').toLowerCase();
  const raw = await withImap(creds => run(creds, N));
  const msgs = parseFetch(String(raw));
  let shown = 0;
  for (const m of msgs) {
    const text = formatMessage(m);
    if (!filter || text.toLowerCase().includes(filter)) { log(text); shown++; }
  }
  log('msgs=' + msgs.length + (filter ? ` shown=${shown}` : ''));
}

if (require.main === module) main(process.argv.slice(2)).catch(e => { console.error('error=' + e.message); process.exit(1); });
module.exports = { fetchCommand, parseFetch, decodeQP, decodeBody, extractLinks, toText, formatMessage, run, main, MAX_TEXT };
