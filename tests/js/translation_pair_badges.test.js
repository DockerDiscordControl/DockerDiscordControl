// Runs the translation pair list (channel_translation.js) in node: a pair the
// bot switched off after five failures carries a badge, a working one none.
// Called from tests/spec/test_an_auto_disabled_pair_says_so.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const js = name => fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js', name), 'utf8');

function render(pair) {
  const list = { innerHTML: '' };
  const ctx = {
    console, t: k => k,
    document: {
      addEventListener() {}, getElementById: id => (id === 'ctPairsList' ? list : null),
      querySelector() { return null; }, querySelectorAll() { return []; },
      createElement: () => ({ textContent: '', get innerHTML() { return String(this.textContent); } }),
    },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(js('escape.js'), ctx);
  vm.runInContext(js('channel_translation.js'), ctx);
  ctx.__pairs = [Object.assign({ id: 'p1', name: 'P', enabled: true, source_channel_id: '1',
    target_channel_id: '2', target_language: 'DE' }, pair)];
  vm.runInContext('ctPairsData = __pairs; renderCTPairs();', ctx);
  return list.innerHTML;
}

const cases = {
  'a pair the bot switched off is marked'() {
    assert.ok(render({ auto_disabled: true }).includes('ct.auto_disabled'), 'no badge on a dead pair');
  },
  'a working pair is not'() {
    assert.ok(!render({ auto_disabled: false }).includes('ct.auto_disabled'), 'a working pair is marked');
  },
};

(async () => {
  let failed = 0;
  for (const [name, fn] of Object.entries(cases)) {
    try { await fn(); console.log('ok     ' + name); }
    catch (e) { failed += 1; console.log('FAILED ' + name + '\n       ' + e.message); }
  }
  process.exit(failed ? 1 : 0);
})();
