'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const m = require('../scripts/mkpayload');
const SCRIPT = path.join(__dirname, '../scripts/mkpayload.js');
const SYMBOL = /[^A-Za-z0-9]/;

test('--alnum: 200 passwords are letters and digits only, with upper, lower and digit', () => {
  for (let i = 0; i < 200; i++) {
    const p = m.makePassword(14, true);
    assert.equal(p.length, 14); assert.doesNotMatch(p, SYMBOL);
    assert.match(p, /[A-Z]/); assert.match(p, /[a-z]/); assert.match(p, /[0-9]/);
  }
});
test('default: 18 chars with at least one symbol, upper, lower and digit', () => {
  for (let i = 0; i < 200; i++) {
    const p = m.makePassword(18, false);
    assert.equal(p.length, 18); assert.match(p, SYMBOL); assert.match(p, /[A-Z]/); assert.match(p, /[a-z]/); assert.match(p, /[0-9]/);
  }
});
test('ambiguous characters are never used', () => {
  for (let i = 0; i < 200; i++) assert.doesNotMatch(m.makePassword(40, false), /[0OIl1]/);
});
test('argument parsing: defaults, explicit length, flag position, errors', () => {
  assert.deepEqual(m.parseArgs(['Item', 'https://x.example/', '--alnum']), { name: 'Item', url: 'https://x.example/', n: 14, alnum: true });
  assert.deepEqual(m.parseArgs(['--alnum', 'Item', 'https://x.example/', '20']), { name: 'Item', url: 'https://x.example/', n: 20, alnum: true });
  assert.equal(m.parseArgs(['Item', 'https://x.example/']).n, 18);
  assert.equal(m.parseArgs(['Item', 'https://x.example/']).alnum, false);
  assert.throws(() => m.parseArgs(['Item']), /usage/);
  assert.throws(() => m.parseArgs(['Item', 'https://x.example/', '--symbols']), /unknown option/);
  assert.throws(() => m.parseArgs(['Item', 'https://x.example/', '4']), /length/);
  assert.throws(() => m.parseArgs(['Item', 'https://x.example/', 'abc']), /length/);
});
test('payload carries the fixed Citations scope and a note only for --alnum', () => {
  const a = m.buildPayload({ name: 'SCC - x.com', url: 'https://x.com/login', n: 14, alnum: true });
  assert.equal(a.organization, 'Senior Care Consulting'); assert.equal(a.collection, 'Citations'); assert.equal(a.name, 'SCC - x.com');
  assert.match(a.notes, /alphanumeric/); assert.doesNotMatch(a.password, SYMBOL);
  assert.equal('notes' in m.buildPayload({ name: 'n', url: 'https://x.com/', n: 18, alnum: false }), false);
});
test('CLI writes the payload file, prints no secret, and fails without TMPDIR', () => {
  const dir = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'mkpayload-test-'));
  const r = spawnSync(process.execPath, [SCRIPT, 'SCC - y.com', 'https://y.com/login', '--alnum'], { env: { ...process.env, TMPDIR: dir }, encoding: 'utf8' });
  assert.equal(r.status, 0);
  const payload = JSON.parse(fs.readFileSync(path.join(dir, 'vaultwarden-login.json'), 'utf8'));
  assert.doesNotMatch(payload.password, SYMBOL); assert.equal(payload.password.length, 14);
  assert.equal(r.stdout.includes(payload.password), false); assert.equal(r.stderr.includes(payload.password), false);
  assert.match(r.stdout, /payload written for SCC - y\.com \(alphanumeric\)/);
  // t_d7a907d5: no TMPDIR (or a POSIX one node cannot see) is no longer a crash; the real temp dir is used.
  const env = { ...process.env }; delete env.TMPDIR;
  const ok2 = spawnSync(process.execPath, [SCRIPT, 'n', 'https://y.com/'], { env, encoding: 'utf8' });
  assert.equal(ok2.status, 0); assert.match(ok2.stdout, /payload written for n/);
  fs.rmSync(path.join(os.tmpdir(), 'vaultwarden-login.json'), { force: true });
  fs.rmSync(dir, { recursive: true, force: true });
});

// ---- t_04751f6a: client profiles (scc default, nm). Dry-run payloads only: no vault call, no live write.
const SCC_OLD = { organization: 'Senior Care Consulting', collection: 'Citations', username: 'listings@seniorcaresolutions.co' };
const scope = p => ({ organization: p.organization, collection: p.collection, username: p.username });
test('SCC default (no flags) payload is exactly the old fixed scope, key order included', () => {
  const p = m.buildPayload({ name: 'SCC - a.com', url: 'https://a.com/', n: 18, alnum: false });
  assert.deepEqual(scope(p), SCC_OLD);
  assert.deepEqual(Object.keys(p), ['organization', 'collection', 'username', 'name', 'url', 'password']);
  const q = m.buildPayload(m.parseArgs(['SCC - a.com', 'https://a.com/']));
  assert.deepEqual(scope(q), SCC_OLD);
  const r = m.buildPayload(m.parseArgs(['SCC - a.com', 'https://a.com/', '--client', 'scc']));
  assert.deepEqual(scope(r), SCC_OLD);
  assert.deepEqual(m.parseArgs(['Item', 'https://x.example/']), { name: 'Item', url: 'https://x.example/', n: 18, alnum: false });
});
test('NM profile: Nacke Media / Citations / listings@nackemedia.com', () => {
  const p = m.buildPayload(m.parseArgs(['NM - example.com', 'https://example.com/login', '--client', 'nm']));
  assert.deepEqual(scope(p), { organization: 'Nacke Media', collection: 'Citations', username: 'listings@nackemedia.com' });
  assert.equal(p.name, 'NM - example.com'); assert.equal(p.url, 'https://example.com/login');
  assert.equal(p.password.length, 18); assert.equal('notes' in p, false);
  const a = m.buildPayload(m.parseArgs(['NM - example.com', 'https://example.com/', '--alnum', '--client', 'nm']));
  assert.match(a.notes, /alphanumeric/); assert.doesNotMatch(a.password, SYMBOL); assert.equal(a.organization, 'Nacke Media');
});
test('NM item names must start "NM - " (an SCC-style name cannot land in the NM org); SCC has no prefix rule', () => {
  assert.throws(() => m.buildPayload(m.parseArgs(['SCC - x.com', 'https://x.com/', '--client', 'nm'])), /must start with "NM - "/);
  assert.throws(() => m.buildPayload(m.parseArgs(['example.com', 'https://x.com/', '--client', 'nm'])), /NM - /);
  assert.doesNotThrow(() => m.buildPayload(m.parseArgs(['anything', 'https://x.com/'])));
});
test('--org/--collection/--username override one field of the client', () => {
  const p = m.buildPayload(m.parseArgs(['NM - e.com', 'https://e.com/', '--client', 'nm', '--collection', 'Citations Test']));
  assert.deepEqual(scope(p), { organization: 'Nacke Media', collection: 'Citations Test', username: 'listings@nackemedia.com' });
  const s = m.buildPayload(m.parseArgs(['SCC - e.com', 'https://e.com/', '--org', 'Other Org', '--username', 'x@y.co']));
  assert.deepEqual(scope(s), { organization: 'Other Org', collection: 'Citations', username: 'x@y.co' });
});
test('bad flags: unknown client, missing or empty value, still unknown option', () => {
  assert.throws(() => m.parseArgs(['n', 'https://x.com/', '--client', 'bre']), /unknown client/);
  assert.throws(() => m.parseArgs(['n', 'https://x.com/', '--client']), /needs a value/);
  assert.throws(() => m.parseArgs(['n', 'https://x.com/', '--org', '--alnum']), /needs a value/);
  assert.throws(() => m.parseArgs(['n', 'https://x.com/', '--org', ' ']), /may not be empty/);
  assert.throws(() => m.parseArgs(['n', 'https://x.com/', '--symbols']), /unknown option/);
});
test('CLI --dry-run for both profiles prints the redacted payload and writes NO file', () => {
  const dir = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'mkpayload-dry-'));
  for (const [args, org, user] of [[['NM - dry.com', 'https://dry.com/login', '--client', 'nm', '--dry-run'], 'Nacke Media', 'listings@nackemedia.com'],
                                   [['SCC - dry.com', 'https://dry.com/login', '--dry-run'], 'Senior Care Consulting', 'listings@seniorcaresolutions.co']]) {
    const r = spawnSync(process.execPath, [SCRIPT, ...args], { env: { ...process.env, TMPDIR: dir }, encoding: 'utf8' });
    assert.equal(r.status, 0, r.stderr);
    const json = JSON.parse(r.stdout.slice(r.stdout.indexOf('{')));
    assert.equal(json.organization, org); assert.equal(json.collection, 'Citations'); assert.equal(json.username, user);
    assert.match(json.password, /^<18 chars redacted>$/); assert.match(r.stdout, /DRY RUN \(nothing written\)/);
    assert.equal(fs.existsSync(path.join(dir, 'vaultwarden-login.json')), false);
  }
  const bad = spawnSync(process.execPath, [SCRIPT, 'SCC - bad.com', 'https://bad.com/', '--client', 'nm', '--dry-run'], { env: { ...process.env, TMPDIR: dir }, encoding: 'utf8' });
  assert.equal(bad.status, 1); assert.match(bad.stderr, /mkpayload=failed item name must start/);
  const live = spawnSync(process.execPath, [SCRIPT, 'NM - live.com', 'https://live.com/', '--client', 'nm'], { env: { ...process.env, TMPDIR: dir }, encoding: 'utf8' });
  const written = JSON.parse(fs.readFileSync(path.join(dir, 'vaultwarden-login.json'), 'utf8'));
  assert.equal(written.organization, 'Nacke Media'); assert.equal(live.stdout.includes(written.password), false);
  fs.rmSync(dir, { recursive: true, force: true });
});
