'use strict';
// Prints the listings@ IMAP login as ONE JSON line {host,port,user,password} on stdout, for job/imap_vault.py to read from the pipe (t_d2f75685).
// Uses the citation-submitter skill's withImap (vault unlocked, item read, vault locked again). The password goes to the pipe only: no file, no argv, no log.
// stderr carries a short reason code, never a secret.
const path = require('node:path');
(async () => {
  try {
    const js = process.argv[2];
    if (!js) throw new Error('missing-helper-path');
    const { withImap } = require(path.resolve(js));
    const out = await withImap(async c => ({ host: c.host, port: c.port, user: c.user, password: c.password }));
    process.stdout.write(JSON.stringify(out) + '\n');
  } catch (error) {
    console.error('imap-vault=failed reason=' + String(error && error.message ? error.message : 'operation-failed').replace(/[^a-z0-9 _-]/gi, '').slice(0, 60));
    process.exitCode = 1;
  }
})();
