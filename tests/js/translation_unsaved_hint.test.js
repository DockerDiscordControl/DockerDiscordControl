// Runs app/static/js/channel_translation.js in node: a changed translation
// setting says it is not saved yet, and leaving the page asks first.
// Called from tests/spec/test_translation_settings_say_they_are_unsaved.py.
//
// THE FINDING (translation audit, 2026-09-26, #10): provider, key, tier,
// region, limits and the two display switches save only through the section's
// own button. They are rightly marked data-saves-itself, so the page's
// "unsaved changes" banner ignores them - and nothing else said anything:
// leaving the page lost the change silently.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

function page() {
  const els = {};
  const el = id => {
    if (!els[id]) {
      const classes = new Set(id === 'ctUnsavedHint' ? ['d-none'] : []);
      els[id] = {
        id, value: '', checked: false, handlers: {},
        addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); },
        classList: {
          add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c),
          toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
        },
      };
    }
    return els[id];
  };
  const winHandlers = {};
  const document = {
    addEventListener() {}, getElementById: el,
    querySelector() { return null; }, querySelectorAll() { return []; },
    createElement: () => ({ textContent: '', get innerHTML() { return ''; } }),
  };
  const ctx = { document, console, t: k => k };
  ctx.window = ctx;
  ctx.addEventListener = (type, fn) => { winHandlers[type] = fn; };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js', 'escape.js'), 'utf8'), ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js', 'channel_translation.js'), 'utf8'), ctx);
  ctx.ctWatchSettings();
  return { ctx, el, winHandlers };
}

const fire = (element, type) => (element.handlers[type] || []).forEach(fn => fn({}));
const hidden = p => p.el('ctUnsavedHint').classList.contains('d-none');

const cases = {
  'a changed setting shows the hint'() {
    const p = page();
    assert.ok(hidden(p), 'the hint shows before anything changed');
    fire(p.el('ctRateLimit'), 'input');
    assert.ok(!hidden(p), 'a changed limit said nothing');
  },
  'every setting of the section counts'() {
    for (const id of ['ctProvider', 'ctApiKey', 'ctDeeplUrl', 'ctMsRegion', 'ctRateLimit',
      'ctMaxTextLength', 'ctShowOriginalLink', 'ctShowProviderFooter']) {
      const p = page();
      fire(p.el(id), id.startsWith('ctShow') || id === 'ctProvider' || id === 'ctDeeplUrl' ? 'change' : 'input');
      assert.ok(!hidden(p), `${id} changed and nothing said so`);
    }
  },
  'saving or loading clears it'() {
    const p = page();
    fire(p.el('ctRateLimit'), 'input');
    p.ctx.ctMarkDirty(false);
    assert.ok(hidden(p));
  },
  'leaving with an unsaved change asks first, a clean page does not'() {
    const p = page();
    const clean = { preventDefault() { this.stopped = true; } };
    p.winHandlers.beforeunload(clean);
    assert.ok(!clean.stopped, 'a clean page asked before leaving');
    fire(p.el('ctRateLimit'), 'input');
    const dirty = { preventDefault() { this.stopped = true; } };
    p.winHandlers.beforeunload(dirty);
    assert.ok(dirty.stopped, 'leaving did not ask');
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(cases)) {
  try { fn(); console.log('ok     ' + name); }
  catch (e) { failed += 1; console.log('FAILED ' + name + '\n       ' + e.message); }
}
process.exit(failed ? 1 : 0);
