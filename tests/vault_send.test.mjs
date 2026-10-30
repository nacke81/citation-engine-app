// t_79c39f75: Send builder + stub bw. No vault, no network.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const V = createRequire(import.meta.url)('../job/vault_send.cjs');
const SECRET = 'hunter2-SECRET-pw';
const item = { id: 'i1', type: 1, name: 'SCC - nextdoor.com', login: { username: 'lea@example.org', password: SECRET } };
const now = new Date('2026-10-30T12:00:00Z');

test('Send settings', () => {
  const s = V.buildSend(item, 'nextdoor.com', now);
  assert.equal(s.type, 0); assert.equal(s.maxAccessCount, 1); assert.equal(s.password, null);
  assert.equal(s.text.hidden, false); assert.equal(s.deletionDate, '2026-11-06T12:00:00.000Z'); assert.equal(s.expirationDate, s.deletionDate);
});

test('createSend: body to stdin as base64, never argv; result has no secret', () => {
  const seen = [];
  const bw = (args, input) => { seen.push({ args, input }); return JSON.stringify({ accessUrl: 'https://vw/#/send/a/K' }); };
  const r = V.createSend(bw, item, 'nextdoor.com', now);
  assert.deepEqual(r, { url: 'https://vw/#/send/a/K', expires_at: '2026-11-06T12:00:00.000Z' });
  assert.deepEqual(seen[0].args, ['send', 'create']);
  assert.ok(!JSON.stringify(seen[0].args).includes(SECRET));
  assert.ok(Buffer.from(seen[0].input, 'base64').toString().includes(SECRET)); // the Send must carry it
  assert.ok(!JSON.stringify(r).includes(SECRET));
});

test('createSend: no accessUrl is an error, message has no secret', () => {
  assert.throws(() => V.createSend(() => '{}', item, 'nextdoor.com', now), e => !String(e.message).includes(SECRET));
});

test('pickItem: exact SCC - <directory>, missing and duplicates fail closed', () => {
  assert.equal(V.pickItem([item], 'nextdoor.com').id, 'i1');
  assert.equal(V.pickItem([item], 'yelp.com'), null);
  assert.equal(V.pickItem([item, { ...item, id: 'i2' }], 'nextdoor.com'), null);
  assert.equal(V.pickItem([{ ...item, deletedDate: 'x' }], 'nextdoor.com'), null);
});
