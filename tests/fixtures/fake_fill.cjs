'use strict';
// Test double for fill helper: bw returns NON-JSON text that contains the secret, to prove it never reaches stderr/log.
const SECRET = process.env.FAKE_SECRET || 'secret';
const mode = process.env.FAKE_BW_MODE;
module.exports = {
  resolveScope: () => ({ org: { id: 'o' }, collection: { id: 'c' } }),
  withVault: async (env, fn) => fn((args) => {
    if (args[0] === 'list') return JSON.stringify([{ id: 'i1', type: 1, name: 'SCC - nextdoor.com', organizationId: 'o', collectionIds: ['c'] }]);
    if (args[0] === 'get') return mode === 'get-item' ? SECRET + ' garbage' : JSON.stringify({ login: { username: 'u', password: SECRET } });
    return SECRET + ' garbage';
  }),
};
