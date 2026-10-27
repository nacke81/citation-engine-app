'use strict';
// List the SCC org Citations collection as JSON {items:[{id,name,uris}]} for job/vault_item.py (t_3ac43137).
// Only id, name and login URIs are put in the output; no secret field is read or printed. Reuses the fill helper's vault session code
// (--fill-js points at vaultwarden-cli-fill.js), so the same unlock/lock and CLI-version checks apply.
const path = require('node:path');
function arg(name) { const i = process.argv.indexOf(name); return i > -1 ? process.argv[i + 1] : undefined; }
(async () => {
  try {
    const fillJs = arg('--fill-js'), organization = arg('--organization'), collection = arg('--collection');
    if (!fillJs || !organization || !collection) throw new Error('missing-options');
    const H = require(path.resolve(fillJs));
    const items = await H.withVault(process.env, async bw => {
      const { org, collection: col } = H.resolveScope(bw, { organization, collection });
      const list = JSON.parse(bw(['list', 'items', '--organizationid', org.id, '--collectionid', col.id]));
      return list
        .filter(e => e.type === 1 && e.organizationId === org.id && e.collectionIds?.includes(col.id) && !e.deletedDate)
        .map(e => ({ id: e.id, name: e.name, uris: (e.login?.uris || []).map(u => u.uri).filter(Boolean) }));
    });
    console.log(JSON.stringify({ items }));
  } catch (error) {
    console.error(`list=failed reason=${error && error.message ? String(error.message).replace(/[^a-z0-9 _-]/gi, '').slice(0, 60) : 'operation-failed'}`);
    process.exitCode = 1;
  }
})();
