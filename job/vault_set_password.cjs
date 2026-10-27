'use strict';
// Set the password of ONE existing Citations item (t_2d15878c). After a site password reset the new password goes into the domain's
// existing Vaultwarden item; this script never creates an item. The new password arrives on STDIN only (never argv, never printed).
//   node vault_set_password.cjs --item-id ID --organization ORG --collection COL --fill-js PATH   < new-password
// Output: `set=success` or `set=failed reason=...` . Exit 1 on failure.
const path = require('node:path');
const fs = require('node:fs');
function arg(name) { const i = process.argv.indexOf(name); return i > -1 ? process.argv[i + 1] : undefined; }
(async () => {
  try {
    const fillJs = arg('--fill-js'), organization = arg('--organization'), collection = arg('--collection'), itemId = arg('--item-id');
    if (!fillJs || !organization || !collection || !itemId) throw new Error('missing-options');
    const pw = fs.readFileSync(0, 'utf8').replace(/[\r\n]+$/, '');
    if (!pw || pw.length < 8) throw new Error('empty-or-short-password');
    const H = require(path.resolve(fillJs));
    await H.withVault(process.env, async bw => {
      const { org, collection: col } = H.resolveScope(bw, { organization, collection });
      const full = JSON.parse(bw(['get', 'item', itemId]));
      if (full.type !== 1 || full.organizationId !== org.id || !full.collectionIds?.includes(col.id) || full.deletedDate) throw new Error('item-not-in-scope');
      full.login.password = pw;
      const encoded = bw(['encode'], JSON.stringify(full)).trim();
      bw(['edit', 'item', itemId], encoded);
      bw(['sync']);
      const back = JSON.parse(bw(['get', 'item', itemId]));
      if (back.login.password !== pw) throw new Error('readback-mismatch');
    });
    console.log('set=success');
  } catch (error) {
    console.error(`set=failed reason=${error && error.message ? String(error.message).replace(/[^a-z0-9 _-]/gi, '').slice(0, 60) : 'operation-failed'}`);
    process.exitCode = 1;
  }
})();
