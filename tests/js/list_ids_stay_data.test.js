// Runs the rule list (auto_actions.js) and the translation pair list
// (channel_translation.js) in node with an id that is an attack, and checks
// that it stays a string. Called from
// tests/spec/test_a_stored_id_cannot_run_script.py.
//
// THE FINDING (translation audit, 2026-09-26, #9): both lists write the id
// into onclick="openRuleEditor('${safeId}')" after an HTML escape that left
// the single quote alone - and even an escaped &#39; is decoded by the
// browser BEFORE the handler runs, so HTML escaping cannot protect a JS
// string there. An id of  x');alert(1);//  ran as script on opening the
// panel. Ids came from the request on create, and a restored backup brings
// its own files.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const EVIL = "x');alert(1);//\" onmouseover=\"alert(2)";
const js = name => fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js', name), 'utf8');

function sandbox() {
  const list = { innerHTML: '' };
  const document = {
    addEventListener() {},
    getElementById: id => (id === 'ctPairsList' ? list : null),
    createElement: () => ({ textContent: '', get innerHTML() {
      return String(this.textContent).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    } }),
    querySelector() { return null; }, querySelectorAll() { return []; },
  };
  const ctx = { document, console, t: k => k };
  ctx.window = ctx;
  vm.createContext(ctx);
  for (const name of ['escape.js', 'rule_targets.js', 'auto_actions.js', 'channel_translation.js']) {
    vm.runInContext(js(name), ctx);
  }
  return { ctx, list };
}

// What the browser does to an attribute value before the handler runs.
const decode = s => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<')
  .replace(/&gt;/g, '>').replace(/&amp;/g, '&');

function handlers(html) {
  return [...html.matchAll(/\s(on[a-z]+)="([^"]*)"/g)].map(m => [m[1], decode(m[2])]);
}

function checkHandlers(html, fn) {
  const found = handlers(html);
  assert.ok(found.some(([, code]) => code.startsWith(fn + '(')), `no ${fn} handler in ${html}`);
  for (const [name, code] of found) {
    assert.ok(name !== 'onmouseover', `the id opened a new attribute: ${html}`);
    const call = /^([A-Za-z]+)\((.*)\)$/.exec(code.replace(/, this\.checked\)$/, ')'));
    if (!call || !/^(openRuleEditor|toggleRuleEnabled|openCTPairEditor|toggleCTPair)$/.test(call[1])) continue;
    // The argument must be ONE JavaScript string literal that reads back as the id.
    assert.strictEqual(JSON.parse(call[2]), EVIL, `${name}="${code}" is not the id as a string`);
  }
}

const cases = {
  'a rule id stays a string'() {
    const { ctx } = sandbox();
    const html = ctx.renderRuleItem({
      id: EVIL, name: 'r', enabled: true, priority: 1,
      trigger: { keywords: [], source_filter: {} }, action: { type: 'NOTIFY', containers: [] },
      metadata: {},
    });
    checkHandlers(html, 'openRuleEditor');
  },
  'a translation pair id stays a string'() {
    const { ctx, list } = sandbox();
    ctx.__pairs = [{ id: EVIL, name: 'p', enabled: true, source_channel_id: '1',
      target_channel_id: '2', target_language: 'DE' }];
    vm.runInContext('ctPairsData = __pairs; renderCTPairs();', ctx);
    checkHandlers(list.innerHTML, 'openCTPairEditor');
  },
};

(async () => {
  let failed = 0;
  for (const [name, fn] of Object.entries(cases)) {
    try { await fn(); console.log('ok     ' + name); }
    catch (e) { failed += 1; console.log('FAILED ' + name + '\n       ' + e.message.split('\n').join('\n       ')); }
  }
  process.exit(failed ? 1 : 0);
})();
