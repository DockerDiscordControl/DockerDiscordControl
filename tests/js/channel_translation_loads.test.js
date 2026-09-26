// Runs app/static/js/channel_translation.js in node: the section's data loads
// as the page loads, not on a first unfold. Called from
// tests/spec/test_channel_translation_is_not_folded_away.py.
//
// THE REQUEST (operator, 2026-09-26): the card was collapsed by default and
// loaded languages, pairs and settings only when it was first unfolded. On a
// tab of its own that only hid the feature and its on/off state.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

function element() {
  return new Proxy({ style: {}, classList: { add() {}, remove() {}, toggle() {} }, dataset: {},
    options: [], children: [], value: '', checked: false, innerHTML: '', textContent: '',
    appendChild() {}, addEventListener() {}, setAttribute() {}, querySelector() { return null; },
    querySelectorAll() { return []; }, remove() {} }, {
    get(target, key) { return key in target ? target[key] : undefined; },
  });
}

async function page() {
  const listeners = {};
  const fetched = [];
  const document = {
    addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
    getElementById() { return element(); },
    querySelector() { return element(); }, querySelectorAll() { return []; },
    createElement() { return element(); }, body: element(),
  };
  const sandbox = {
    document, console: { log() {}, debug() {}, warn() {}, error() {} },
    setTimeout() {}, t: key => key,
    fetch: async (url) => {
      fetched.push(String(url));
      return { ok: true, status: 200, json: async () => ({ success: true, languages: [], pairs: [], settings: {} }) };
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
    'channel_translation.js'), 'utf8'), sandbox);
  for (const handler of listeners.DOMContentLoaded || []) { await handler(); }
  return fetched;
}

const cases = {
  async 'languages, pairs and settings load with the page'() {
    const fetched = await page();
    for (const route of ['/api/translation/languages', '/api/translation/pairs', '/api/translation/settings']) {
      assert.ok(fetched.includes(route), `${route} was not loaded: ${JSON.stringify(fetched)}`);
    }
  },
  async 'nothing waits for a collapse event'() {
    const source = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
      'channel_translation.js'), 'utf8');
    assert.ok(!source.includes('show.bs.collapse'), 'loading still hangs on unfolding');
  },
};

(async () => {
  let failed = 0;
  for (const [name, run] of Object.entries(cases)) {
    try {
      await run();
      console.log('ok   - ' + name);
    } catch (e) {
      failed += 1;
      console.log('FAIL - ' + name + ': ' + e.message);
    }
  }
  process.exit(failed === 0 ? 0 : 1);
})();
