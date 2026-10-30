'use strict';
// One-time Vaultwarden Send holding ONE directory login, for the client to sign in herself (t_79c39f75).
// Runs inside the fill helper's withVault (same per-seat unlock/lock, bw 2026.7.0 check). The secret is read in memory,
// put in the Send body, and sent to `bw send create` on STDIN (base64 JSON), never argv. stdout is ONE json line {url, expires_at};
// stderr/exit carry only a short reason code. Exit 3 = item missing/ambiguous (fail closed), 1 = anything else.
const path = require('node:path');
const DAYS = 7;

function buildSend(item, directory, now) {
  const due = new Date(now.getTime() + DAYS * 86400000).toISOString();
  const login = item.login || {};
  const text = `Directory: ${directory}\nUsername: ${login.username || ''}\nPassword: ${login.password || ''}`;
  return {
    name: `Sign-in ${directory}`, notes: null, type: 0, text: { text, hidden: false }, file: null,
    maxAccessCount: 1, deletionDate: due, expirationDate: due, password: null, disabled: false, hideEmail: false,
  };
}

function pickItem(list, directory) {
  const want = `scc - ${String(directory).toLowerCase()}`;
  const hit = list.filter(e => e.type === 1 && !e.deletedDate && String(e.name || '').toLowerCase() === want);
  return hit.length === 1 ? hit[0] : null;
}

// bw: (args, stdinText) => stdout. Returns {url, expires_at}; the Send body is never returned or logged.
function createSend(bw, item, directory, now = new Date()) {
  const send = buildSend(item, directory, now);
  const out = JSON.parse(bw(['send', 'create'], Buffer.from(JSON.stringify(send)).toString('base64')));
  if (!out || !out.accessUrl) throw new Error('send-no-url');
  return { url: out.accessUrl, expires_at: send.expirationDate };
}

function arg(name) { const i = process.argv.indexOf(name); return i > -1 ? process.argv[i + 1] : undefined; }

async function main() {
  const fillJs = arg('--fill-js'), organization = arg('--organization'), collection = arg('--collection'), directory = arg('--directory');
  if (!fillJs || !organization || !collection || !directory) throw new Error('missing-options');
  const H = require(path.resolve(fillJs));
  return H.withVault(process.env, async bw => {
    const { org, collection: col } = H.resolveScope(bw, { organization, collection });
    const list = JSON.parse(bw(['list', 'items', '--organizationid', org.id, '--collectionid', col.id]))
      .filter(e => e.organizationId === org.id && e.collectionIds?.includes(col.id));
    const hit = pickItem(list, directory);
    if (!hit) { const e = new Error('item-missing'); e.code = 3; throw e; }
    const full = JSON.parse(bw(['get', 'item', hit.id]));
    if (!full.login || !full.login.password) { const e = new Error('item-missing'); e.code = 3; throw e; }
    const r = createSend(bw, full, directory);
    full.login.password = undefined;
    return r;
  });
}

module.exports = { buildSend, pickItem, createSend, DAYS };

if (require.main === module) {
  main().then(r => console.log(JSON.stringify(r))).catch(error => {
    const reason = error && error.message ? String(error.message).replace(/[^a-z0-9 _-]/gi, '').slice(0, 60) : 'operation-failed';
    console.error(`send=failed reason=${reason}`);
    process.exitCode = error && error.code === 3 ? 3 : 1;
  });
}
