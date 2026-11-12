'use strict';
// Print the LOGIN USERNAME of one Citations-collection item as JSON {"username": "..."} for job/verify_send.py (t_218b03ef).
// The username is the login email (not a secret). The password is never read into the output: the item is fetched through the fill
// helper's own readItem (same scope, origin and deletion checks, same unlock/lock) and the password field is cleared before anything prints.
// Usage: node vault_username.cjs --fill-js <vaultwarden-cli-fill.js> --organization <org> --collection <col> --name <item> --url <signin url>
const path = require('node:path');
function arg(name) { const i = process.argv.indexOf(name); return i > -1 ? process.argv[i + 1] : undefined; }
(async () => {
  try {
    const fillJs = arg('--fill-js'), organization = arg('--organization'), collection = arg('--collection'), name = arg('--name'), url = arg('--url');
    if (!fillJs || !organization || !collection || !name || !url) throw new Error('missing-options');
    const H = require(path.resolve(fillJs));
    const username = await H.withVault(process.env, async bw => {
      const item = H.readItem(bw, { organization, collection, name, url });
      const u = typeof item.login?.username === 'string' ? item.login.username : '';
      item.login.password = undefined;
      return u;
    });
    console.log(JSON.stringify({ username }));
  } catch (error) {
    console.error(`username=failed reason=${error && error.message ? String(error.message).replace(/[^a-z0-9 _-]/gi, '').slice(0, 60) : 'operation-failed'}`);
    process.exitCode = 1;
  }
})();
