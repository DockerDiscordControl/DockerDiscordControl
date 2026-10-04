// Runs app/static/js/config-ui.js in node: the info dialog's "announce
// player joins" box is filled from the container's hidden query_joins_<name>
// field and written back to it on save.
// Called from tests/spec/test_join_notices_are_chosen_per_container_in_the_dialog.py.
//
// THE OPERATOR (2026-10-04): join notices are settable per container in the
// web panel. A container saved before the setting existed has no value in the
// field - and counts as on.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

function page(hiddenValue) {
  const hidden = { value: hiddenValue };
  const box = { checked: null };
  const ids = {
    'modal-container-name': { value: 'Valheim' },
    'modal-query-joins': box,
    'docker-container-list': { dispatchEvent() {} },
  };
  const document = {
    addEventListener() {},
    getElementById: id => ids[id] || null,
    querySelector: selector => (selector === 'input[name="query_joins_Valheim"]' ? hidden : null),
    querySelectorAll: () => [],
    createElement: () => ({ style: {}, appendChild() {} }),
    createTextNode: text => text,
    body: { appendChild() {} },
  };
  const sandbox = { document, console, setTimeout() {}, t: key => key, Event: function (type) { this.type = type; } };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
    'config-ui.js'), 'utf8'), sandbox);
  return { sandbox, hidden, box };
}

const cases = {
  'a saved "0" opens unticked'() {
    const { sandbox, box } = page('0');
    sandbox.openContainerInfoModal('Valheim');
    assert.strictEqual(box.checked, false);
  },
  'a container saved before the setting opens ticked'() {
    const { sandbox, box } = page('');
    sandbox.openContainerInfoModal('Valheim');
    assert.strictEqual(box.checked, true);
  },
  'saving writes the box back'() {
    const { sandbox, hidden, box } = page('1');
    sandbox.openContainerInfoModal('Valheim');
    box.checked = false;
    sandbox.saveContainerInfo();
    assert.strictEqual(hidden.value, '0');
    box.checked = true;
    sandbox.saveContainerInfo();
    assert.strictEqual(hidden.value, '1');
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
