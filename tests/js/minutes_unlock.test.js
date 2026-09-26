// Runs app/static/js/config-ui.js in node: ticking Refresh or Recreate in a
// channel row unlocks that row's minutes field - in a SAVED row too.
// Called from tests/spec/test_ticking_refresh_unlocks_its_minutes.py.
//
// THE FINDING (audit 2026-09-26): the template renders the minutes fields
// `disabled` while their box is unticked, and the only listeners that unlocked
// them were attached to rows added with the + button. For a channel already
// saved, ticking the box left the field locked, and the save sent the stale
// value. The page-wide handler that once covered saved rows was bound to a
// table id that no longer exists.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

function page() {
  const listeners = {};
  const document = {
    addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push(handler); },
    getElementById() { return null; }, querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() { return { style: {}, appendChild() {} }; },
    body: { appendChild() {} },
  };
  const sandbox = { document, console, setTimeout() {}, t: key => key };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
    'config-ui.js'), 'utf8'), sandbox);
  (listeners.DOMContentLoaded || []).forEach(handler => handler());
  const fire = (type, target) => (listeners[type] || []).forEach(handler => handler({ target }));
  return { fire };
}

// A row as the template renders it for a saved channel: box unticked, field disabled.
function savedRow(boxClass, fieldClass) {
  const field = { disabled: true };
  const row = { querySelector: selector => (selector === fieldClass ? field : null) };
  const box = {
    checked: false,
    classList: { contains: name => name === boxClass.slice(1) },
    matches: selector => selector.split(',').map(s => s.trim()).includes(boxClass),
    getAttribute: name => (name === 'data-target-input' ? fieldClass : null),
    closest: selector => (selector === 'tr' ? row : null),
  };
  return { box, field };
}

const cases = {
  'ticking Refresh in a saved row unlocks its interval'() {
    const { fire } = page();
    const { box, field } = savedRow('.auto-refresh-checkbox', '.interval-minutes-input');
    box.checked = true;
    fire('change', box);
    assert.strictEqual(field.disabled, false);
  },
  'ticking Recreate in a saved row unlocks its timeout'() {
    const { fire } = page();
    const { box, field } = savedRow('.recreate-checkbox', '.inactivity-minutes-input');
    box.checked = true;
    fire('change', box);
    assert.strictEqual(field.disabled, false);
  },
  'unticking locks it again'() {
    const { fire } = page();
    const { box, field } = savedRow('.auto-refresh-checkbox', '.interval-minutes-input');
    field.disabled = false;
    box.checked = false;
    fire('change', box);
    assert.strictEqual(field.disabled, true);
  },
  'another checkbox leaves the field alone'() {
    const { fire } = page();
    const { field } = savedRow('.auto-refresh-checkbox', '.interval-minutes-input');
    const other = savedRow('.something-else', '.interval-minutes-input').box;
    other.checked = true;
    fire('change', other);
    assert.strictEqual(field.disabled, true);
  },
};

let failed = 0;
for (const [name, run] of Object.entries(cases)) {
  try {
    run();
    console.log('ok   - ' + name);
  } catch (e) {
    failed += 1;
    console.log('FAIL - ' + name + ': ' + e.message);
  }
}
process.exit(failed === 0 ? 0 : 1);
