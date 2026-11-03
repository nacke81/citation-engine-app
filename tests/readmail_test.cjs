'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const r = require('../job/readmail.cjs');

const VERIFY = 'https://www.example-dir.com/verify?token=ABC123&uid=77&next=%2Fdashboard';
// A long HTML mail: ~300 KB of tracking table padding, then the verify link at the very END (the old 12000-byte fetch / 14000-char print lost it).
function longHtmlMail(padRows = 3000) {
  const row = '<tr><td style=3D"padding:0 0 12px 0;font-family:Arial">Weekly digest item with some filler text so the mail is large</td></tr>\r\n';
  const qpHtml = '<html><body><table>\r\n' + row.repeat(padRows) + '</table><p>Please <a href=3D"' + VERIFY.replace(/&/g, '&amp;').replace(/=/g, '=3D') + '">confirm your email</a></p>'
    + '<a href=3D"https://www.example-dir.com/unsubscribe?u=3D5">Unsubscribe</a><img src=3D"https://cdn.example-dir.com/open/pixel.png"></body></html>\r\n';
  return qpHtml;
}
function fetchResponse(seq, header, body) {
  return `* ${seq} FETCH (BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {${Buffer.byteLength(header, 'latin1')}}\r\n${header} BODY[TEXT] {${Buffer.byteLength(body, 'latin1')}}\r\n${body})\r\n`;
}
const HDR = 'From: no-reply@example-dir.com\r\nSubject: Confirm your email\r\nDate: Sat, 25 Oct 2026 10:00:00 -0500\r\n\r\n';

test('fetch command asks for the whole body: no partial <0.N> range', () => {
  const c = r.fetchCommand('a3', 4, 8);
  assert.match(c, /BODY\.PEEK\[TEXT\]/); assert.doesNotMatch(c, /<\d+\.\d+>/); assert.doesNotMatch(c, /60000|12000/);
  assert.match(c, /^a3 FETCH 4:8 /);
});
test('long HTML mail fixture is really longer than both old limits', () => {
  const b = longHtmlMail();
  assert.ok(b.length > 200000, 'fixture is ' + b.length);
  assert.ok(b.indexOf('token=3DABC123') > 14000 * 4, 'verify link sits far past the old 12000-byte / 14000-char cut');
});
test('parseFetch reads IMAP literals by byte count, including a 300 KB body, and a 2nd message', () => {
  const body = longHtmlMail();
  const raw = fetchResponse(7, HDR, body) + fetchResponse(8, HDR.replace('Confirm', 'Second'), 'short body\r\n') + 'a3 OK done\r\n';
  const msgs = r.parseFetch(raw);
  assert.equal(msgs.length, 2); assert.equal(msgs[0].seq, 7); assert.equal(msgs[0].body, body); assert.equal(msgs[0].truncated, false);
  assert.match(msgs[1].header, /Second/); assert.equal(msgs[1].body, 'short body\r\n');
});
test('a literal that contains "* 9 FETCH (" text does not start a phantom message', () => {
  const body = 'hello\r\n* 9 FETCH (BODY[TEXT] {3}\r\nabc\r\nbye\r\n';
  const msgs = r.parseFetch(fetchResponse(1, HDR, body));
  assert.equal(msgs.length, 1); assert.equal(msgs[0].body, body);
});
test('a body cut short by the server is flagged', () => {
  const raw = '* 1 FETCH (BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {5}\r\nhello BODY[TEXT] {1000}\r\nonly part';
  const m = r.parseFetch(raw)[0];
  assert.equal(m.truncated, true);
  assert.match(r.formatMessage(m), /SERVER CUT THE BODY SHORT/);
});
test('verify link at the very end of a long mail is extracted, decoded and listed FIRST', () => {
  const out = r.formatMessage(r.parseFetch(fetchResponse(1, HDR, longHtmlMail()))[0]);
  const links = out.split('TEXT:')[0];
  assert.ok(links.includes(VERIFY), 'full verify URL with & and %2F intact');
  assert.match(links, /LINKS \(\d+\):\n  \[1\] https:\/\/www\.example-dir\.com\/verify\?token=ABC123/);
  const order = links.split('\n').filter(l => /^\s+\[\d+\]/.test(l));
  assert.ok(order.findIndex(l => l.includes('/verify?')) < order.findIndex(l => l.includes('unsubscribe')), 'verify before unsubscribe');
  assert.ok(order.findIndex(l => l.includes('/verify?')) < order.findIndex(l => l.includes('pixel.png')), 'verify before tracking pixel');
});
test('text is capped but links are not lost, and the cap is disclosed', () => {
  const out = r.formatMessage(r.parseFetch(fetchResponse(1, HDR, longHtmlMail()))[0], 2000);
  assert.ok(out.includes(VERIFY));
  assert.match(out, /text cut at 2000 of \d+ chars; every link above was read from the full body/);
  const text = out.split('TEXT:\n')[1];
  assert.ok(text.length < 2000 + 400);
});
test('default text cap is far above the old 14000', () => { assert.ok(r.MAX_TEXT >= 50000); });
test('header is decoded and printed; body_chars is the full length', () => {
  const body = longHtmlMail(); const out = r.formatMessage(r.parseFetch(fetchResponse(1, HDR, body))[0]);
  assert.match(out, /Subject: Confirm your email/); assert.match(out, /From: no-reply@example-dir\.com/);
  const n = Number(/body_chars=(\d+)/.exec(out)[1]); assert.ok(n > 200000);
});
test('multipart: base64 text part and QP html part are decoded, image parts skipped', () => {
  const b64 = Buffer.from('Your code is 482913. Open https://dir.example/confirm?c=482913&x=1 now.').toString('base64').replace(/(.{60})/g, '$1\r\n');
  const body = '--BOUND\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\n\r\n' + b64 + '\r\n'
    + '--BOUND\r\nContent-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n<a href=3D"https://dir.example/activate?k=3Dz9">go</a>\r\n'
    + '--BOUND\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n\r\nQUJDREVGR0g=\r\n--BOUND--\r\n';
  const out = r.formatMessage(r.parseFetch(fetchResponse(1, HDR, body))[0]);
  assert.match(out, /Your code is 482913/); assert.ok(out.includes('https://dir.example/confirm?c=482913&x=1'));
  assert.ok(out.includes('https://dir.example/activate?k=z9')); assert.doesNotMatch(out, /QUJDREVG|ABCDEFGH/);
});
test('plain-text mail with a bare URL', () => {
  const out = r.formatMessage(r.parseFetch(fetchResponse(1, HDR, 'Click: https://dir.example/v?t=1.\r\nThanks\r\n'))[0]);
  assert.ok(out.includes('[1] https://dir.example/v?t=1')); assert.doesNotMatch(out, /v\?t=1\.\n/);
});
test('extractLinks dedupes and unescapes html entities', () => {
  const l = r.extractLinks('<a href="https://a.example/x?a=1&amp;b=2">x</a> https://a.example/x?a=1&b=2');
  assert.deepEqual(l, ['https://a.example/x?a=1&b=2']);
});
test('end to end with a fake TLS socket delivering the response in small chunks; prints the end-of-mail link and filter works', async () => {
  const body = longHtmlMail(); const resp = fetchResponse(3, HDR, body) + 'a3 OK Fetch completed\r\n';
  const sent = [];
  function connect() {
    const s = new EventEmitter(); s.setTimeout = () => {}; s.destroy = () => s.emit('close');
    s.write = line => {
      sent.push(line.trim());
      if (/LOGIN/.test(line)) setImmediate(() => s.emit('data', Buffer.from('a1 OK logged in\r\n')));
      else if (/EXAMINE/.test(line)) setImmediate(() => s.emit('data', Buffer.from('* 3 EXISTS\r\na2 OK [READ-ONLY] done\r\n')));
      else if (/FETCH/.test(line)) setImmediate(() => { for (let i = 0; i < resp.length; i += 4096) s.emit('data', Buffer.from(resp.slice(i, i + 4096), 'latin1')); });
      else if (/LOGOUT/.test(line)) setImmediate(() => s.emit('data', Buffer.from('* BYE\r\na4 OK\r\n')));
    };
    setImmediate(() => s.emit('data', Buffer.from('* OK ready\r\n')));
    return s;
  }
  const lines = [];
  const withImap = async fn => fn({ host: 'h', port: 993, user: 'u', password: 'p' });
  const wrapped = async fn => withImap(c => r.run(c, 5, connect));
  await r.main(['5', 'confirm your email'], wrapped, l => lines.push(l));
  const all = lines.join('\n');
  assert.ok(all.includes(VERIFY)); assert.match(all, /msgs=1 shown=1/);
  assert.ok(sent.some(s => /EXAMINE INBOX/.test(s)), 'read-only EXAMINE');
  assert.ok(!sent.some(s => /\bSELECT\b|STORE|\\Seen|EXPUNGE|DELETE/.test(s)), 'no write command');
  assert.ok(sent.some(s => /FETCH 1:3 .*BODY\.PEEK\[TEXT\]\)/.test(s)), sent.join(' | '));
  const none = []; await r.main(['5', 'no such text'], wrapped, l => none.push(l));
  assert.match(none.join('\n'), /msgs=1 shown=0/); assert.doesNotMatch(none.join('\n'), /LINKS/);
});

// t_57178c17: a plain (non-QP) body whose link carries activateid=<hex-looking value> must come out byte-exact (=20 / =AB were decoded as a space / a byte).
test('plain body link with activateid=20.. and =AB.. is byte-exact; QP bodies still decode', () => {
  const L1 = 'https://www.example-dir.com/activate?activateid=2043ab9f&u=1';
  const L2 = 'https://www.example-dir.com/activate?activateid=AB12CD34&u=1';
  const plain = `Hello\r\nClick ${L1}\r\nor ${L2}\r\n`;
  const msg = { seq: 1, header: 'Subject: Activate\r\nContent-Transfer-Encoding: 7bit\r\n\r\n', body: plain, truncated: false };
  const out = r.formatMessage(msg);
  assert.ok(out.includes(L1), out); assert.ok(out.includes(L2), out);
  assert.doesNotMatch(out, /activateid /);
  // no CTE header at all: still byte-exact (no =3D / soft-break evidence of QP)
  const out2 = r.formatMessage({ seq: 2, header: 'Subject: A\r\n\r\n', body: plain, truncated: false });
  assert.ok(out2.includes(L1) && out2.includes(L2), out2);
  // a QP body (declared) still decodes =3D and =20
  const qp = r.formatMessage({ seq: 3, header: 'Content-Transfer-Encoding: quoted-printable\r\n\r\n', body: 'Go: https://x.example/a?activateid=3D2043ab9f\r\n', truncated: false });
  assert.ok(qp.includes('https://x.example/a?activateid=2043ab9f'), qp);
  // a QP body with no header but =3D evidence still decodes
  const qp2 = r.formatMessage({ seq: 4, header: 'Subject: Q\r\n\r\n', body: '<a href=3D"https://x.example/a?activateid=3D2043ab9f">go</a>\r\n', truncated: false });
  assert.ok(qp2.includes('https://x.example/a?activateid=2043ab9f'), qp2);
});
