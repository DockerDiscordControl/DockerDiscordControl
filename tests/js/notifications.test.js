// Runs the settings page's scripts in node, in the order config.html loads
// them, and asks: does showNotification put anything in front of the operator?
// Called from tests/spec/test_a_notification_reaches_the_screen.py.
//
// THE FINDING (audit 2026-09-26): three scripts each declared a global
// showNotification. The LAST one loaded wins, and that was
// advanced_settings_modal.js, whose body was a console.log. So every message
// of the channel-translation editor and the auto-action dialog - "saved",
// "deleted", and the errors that explain why Save did nothing - went to the
// browser console only.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const JS = path.join(__dirname, '..', '..', 'app', 'static', 'js');
// config.html: mech_panel.js in the head, the advanced dialog's script with
// its include, config-ui.js from _scripts.html at the end.
const ORDER = ['mech_panel.js', 'advanced_settings_modal.js', 'config-ui.js'];

function page() {
  const appended = [];
  const element = () => ({
    style: {}, classList: { add() {}, remove() {} }, appendChild() {}, setAttribute() {},
    addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
  });
  const document = {
    addEventListener() {}, getElementById() { return null; }, querySelector() { return null; },
    querySelectorAll() { return []; }, createElement: element,
    head: { appendChild() {} },
    body: { appendChild(node) { appended.push(node); }, contains() { return true; }, removeChild() {} },
  };
  const logged = [];
  const sandbox = {
    document, setTimeout() {}, setInterval() {}, clearInterval() {}, t: key => key,
    fetch: () => Promise.resolve(), localStorage: { getItem() { return null; }, setItem() {} },
    console: { log: (...a) => logged.push(a.join(' ')), warn() {}, error() {}, debug() {} },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  for (const name of ORDER) {
    vm.runInContext(fs.readFileSync(path.join(JS, name), 'utf8'), sandbox, { filename: name });
  }
  return { sandbox, appended, logged };
}

const cases = {
  'a notification is shown, not only logged'() {
    const { sandbox, appended } = page();
    sandbox.showNotification('Rule saved', 'success');
    assert.strictEqual(appended.length, 1, 'nothing was put on the page');
    assert.ok(appended[0].innerHTML.includes('Rule saved'), appended[0].innerHTML);
  },
  'an error is shown as one'() {
    const { sandbox, appended } = page();
    sandbox.showNotification('Channel ID is invalid', 'danger');
    assert.ok(appended[0].innerHTML.includes('text-danger'), appended[0].innerHTML);
  },
  'the text is text, not markup'() {
    const { sandbox, appended } = page();
    sandbox.showNotification('<img src=x onerror=alert(1)>', 'error');
    assert.ok(!appended[0].innerHTML.includes('<img'), appended[0].innerHTML);
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
