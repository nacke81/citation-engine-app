'use strict';
// Credential-free copy of submitter's real secure-fill helper. No vault, browser or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const vm = require('node:vm');
const snapshot = path.join(__dirname, 'fixtures/submitter-secure-fill/vaultwarden-cli-fill.js');
const actual = process.env.CE_FILL_JS;
if (actual && fs.existsSync(actual)) {
  const hash = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
  assert.equal(hash(snapshot), hash(actual), 'submitter helper drifted from tested snapshot; update fixture only after review');
}
const helper = require(actual && fs.existsSync(actual) ? actual : snapshot);
const url = 'https://www.cylex.us.com/register';
const options = { url, field: 'input[type=password]' };
class Input {
  constructor(visible) { this.type = 'password'; this.isConnected = true; this.visible = visible; this.events = []; }
  getClientRects() { return this.visible ? [{}] : []; }
  dispatchEvent(event) { this.events.push(event.type); }
}
Object.defineProperty(Input.prototype, 'value', {get() { return this._value; }, set(v) { this._value = v; }});
function dom(expression, tab) {
  const context = {
    HTMLInputElement: Input, Event: class { constructor(type) { this.type = type; } },
    document: { querySelectorAll(selector) {
      assert.equal(selector, 'input[type=password]');
      return tab.fields;
    }, hasFocus: () => tab.focus, visibilityState: tab.visible ? 'visible' : 'hidden' },
    location: {href: tab.url}, getComputedStyle: el => ({visibility: el.visible ? 'visible' : 'hidden'})
  };
  return vm.runInNewContext(expression, context);
}
function fakeCdp(tabs) {
  let current;
  const calls = [];
  return {calls, async call(method, params, sessionId) {
    calls.push({method, sessionId});
    if (method === 'Target.attachToTarget') return {sessionId: params.targetId};
    current = tabs[sessionId];
    if (params.expression.includes('document.hasFocus()'))
      return {result: {value: {focus: current.focus, visible: current.visible}}};
    return {result: {value: dom(params.expression, current)}};
  }};
}
(async () => {
  const stale = {url, focus: false, visible: false, fields: [new Input(false)]};
  const current = {url, focus: true, visible: true, fields: [new Input(false), new Input(true)]};
  const cdp = fakeCdp({stale, current});
  const target = await helper.pickFocusedTarget(cdp, [
    {targetId: 'stale', type: 'page', url}, {targetId: 'current', type: 'page', url}
  ]);
  assert.equal(target.sessionId, 'current');
  // Wrong same-URL tab would time out; pre-fix first-match on current tab
  // also waits on the hidden duplicate rather than selecting the visible one.
  assert.equal(dom(helper.readinessExpression(options), stale), 'waiting');
  await assert.rejects(helper.waitForField(cdp, options, 'stale', 0), /browser-field-not-rendered/);
  assert.equal(current.fields[0].getClientRects().length, 0);
  assert.equal(dom(helper.readinessExpression(options), current), 'ready');
  await helper.waitForField(cdp, options, target.sessionId, 100);
  const fixtureValue = 'dummy-fixture-only';
  assert.equal(dom(helper.fillExpression(options, fixtureValue), current), true);
  assert.equal(dom(helper.retainedExpression(options, fixtureValue), current), true);
  assert.deepEqual(current.fields[1].events, ['input', 'change']);
  assert.equal(current.fields[0].value, undefined);
  console.log('PASS current focused same-URL tab, visible duplicate selected; pre-fix hidden-first would fail');
  current.url = 'https://www.cylex.us.com/other-path';
  assert.equal(dom(helper.readinessExpression(options), current), 'refused');
  await assert.rejects(helper.waitForField(cdp, options, target.sessionId, 100), /browser-fill-refused/);
  assert.equal(dom(helper.fillExpression(options, fixtureValue), current), false);
  console.log('PASS navigation/path mismatch refuses before fill');
  const bw = args => {
    if (args[0] === 'list' && args[1] === 'organizations') return JSON.stringify([{id:'o', name:'Org'}]);
    if (args[0] === 'list' && args[1] === 'collections') return JSON.stringify([{id:'c', name:'Collection', organizationId:'o'}]);
    if (args[0] === 'list' && args[1] === 'items') return JSON.stringify([{id:'i', name:'Fixture', type:1, organizationId:'o', collectionIds:['c']}]);
    return JSON.stringify({id:'i', name:'Fixture', type:1, organizationId:'o', collectionIds:['c'], login:{password:'dummy-fixture-only', uris:[{uri:'https://other.example/'}]}});
  };
  assert.throws(() => helper.readItem(bw, {...options, organization:'Org', collection:'Collection', name:'Fixture'}), /item-origin-mismatch/);
  console.log('PASS vault item origin mismatch refused');
})().catch(error => {console.error(error); process.exitCode = 1;});
