'use strict';
// usage: node mkpayload.js "<item name>" "<login url>" [len] [--alnum] [--client scc|nm] [--org X] [--collection X] [--username X] [--dry-run]
// Writes $TMPDIR/vaultwarden-login.json (the payload-file input of vaultwarden-cli-write.js) with a random site-safe password. Prints nothing secret.
//   default  length 18, upper+lower+digit+one of !@#$%
//   --alnum  length 14, upper+lower+digit only (for sites that reject symbols, e.g. 2findlocal). t_d13bd638
// Ambiguous characters (0 O 1 l I) are left out.
//   --client scc  (default) org Senior Care Consulting / collection Citations / username listings@seniorcaresolutions.co
//   --client nm   org Nacke Media / collection Citations / username listings@nackemedia.com / item name must start "NM - "   (t_04751f6a)
//   --org / --collection / --username override one field of the chosen client. No --client = SCC, so every existing call is unchanged.
//   --dry-run  prints the payload with the password redacted and the target file, writes NOTHING (no file, no vault call).
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const U = 'ABCDEFGHJKLMNPQRSTUVWXYZ', L = 'abcdefghijkmnpqrstuvwxyz', D = '23456789', S = '!@#$%';
const CLIENTS = {
  scc: { organization: 'Senior Care Consulting', collection: 'Citations', username: 'listings@seniorcaresolutions.co', prefix: null },
  nm: { organization: 'Nacke Media', collection: 'Citations', username: 'listings@nackemedia.com', prefix: 'NM - ' },
};
const VALUE_FLAGS = { '--client': 'client', '--org': 'org', '--collection': 'collection', '--username': 'username' };

function parseArgs(argv) {
  const rest = [];
  const extra = {};
  let alnum = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--alnum') { alnum = true; continue; }
    if (a === '--dry-run') { extra.dryRun = true; continue; }
    if (VALUE_FLAGS[a]) {
      const v = argv[i + 1];
      if (v === undefined || v.startsWith('--')) throw new Error(a + ' needs a value');
      extra[VALUE_FLAGS[a]] = v; i++; continue;
    }
    if (a.startsWith('--')) throw new Error('unknown option ' + a);
    rest.push(a);
  }
  if (extra.client !== undefined && !CLIENTS[extra.client]) throw new Error('unknown client ' + extra.client + ' (scc or nm)');
  for (const k of ['org', 'collection', 'username']) if (k in extra && !extra[k].trim()) throw new Error('--' + k + ' may not be empty');
  const [name, url, len] = rest;
  if (!name || !url) throw new Error('usage: mkpayload.js "<item name>" "<login url>" [len] [--alnum] [--client scc|nm] [--org X] [--collection X] [--username X] [--dry-run]');
  const n = len === undefined ? (alnum ? 14 : 18) : Number(len);
  if (!Number.isInteger(n) || n < 8 || n > 64) throw new Error('length must be an integer from 8 to 64');
  return { name, url, n, alnum, ...extra };
}

function makePassword(n, alnum, rng = crypto.randomInt) {
  const pick = s => s[rng(s.length)];
  const sets = alnum ? [U, L, D] : [U, L, D, S];
  const all = sets.join('');
  const a = sets.map(pick);
  while (a.length < n) a.push(pick(all));
  for (let i = a.length - 1; i > 0; i--) { const j = rng(i + 1); [a[i], a[j]] = [a[j], a[i]]; }
  return a.join('');
}

function scope(opts) {
  const c = CLIENTS[opts.client || 'scc'];
  if (!c) throw new Error('unknown client ' + opts.client);
  if (c.prefix && !String(opts.name).startsWith(c.prefix)) throw new Error('item name must start with "' + c.prefix + '" for client ' + opts.client);
  return { organization: opts.org || c.organization, collection: opts.collection || c.collection, username: opts.username || c.username };
}

function buildPayload(opts, rng) {
  const { name, url, n, alnum } = opts;
  const payload = { ...scope(opts), name, url, password: makePassword(n, alnum, rng) };
  if (alnum) payload.notes = 'alphanumeric-only password (site rejects symbols)';
  return payload;
}

function main(argv, env = process.env) {
  const opts = parseArgs(argv);
  const payload = buildPayload(opts);
  const dir = require('./tmp-dir').realTmpDir(env);   // POSIX TMPDIR=/tmp from git-bash is not a real dir for node (t_d7a907d5)
  const file = path.join(dir, 'vaultwarden-login.json');
  if (opts.dryRun) return 'DRY RUN (nothing written) would write ' + file + ' ' + JSON.stringify({ ...payload, password: '<' + payload.password.length + ' chars redacted>' });
  fs.writeFileSync(file, JSON.stringify(payload));
  return 'payload written for ' + opts.name + (opts.alnum ? ' (alphanumeric)' : '');
}

if (require.main === module) {
  try { console.log(main(process.argv.slice(2))); } catch (e) { console.error('mkpayload=failed ' + e.message); process.exitCode = 1; }
}
module.exports = { parseArgs, makePassword, buildPayload, main, CLIENTS };
