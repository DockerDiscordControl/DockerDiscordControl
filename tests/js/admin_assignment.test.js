// Runs the label rule of app/static/js/config-ui.js in node: what an operator
// reads in the per-admin assignment. Called from
// tests/spec/test_an_admin_can_be_assigned_a_group.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

// config-ui.js is a page script: it reaches for document as it loads. Only the
// pure label rule is taken out of it, by name, the way the page defines it.
const source = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'config-ui.js'), 'utf8');
const start = source.indexOf('function adminAssignmentLabel');
assert.ok(start > -1, 'adminAssignmentLabel is gone');
const end = source.indexOf('\nfunction ', start + 1);
const sandbox = { console };
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end === -1 ? undefined : end), sandbox);
const { adminAssignmentLabel } = sandbox;

const cases = {
  'a container is read as itself'() {
    assert.strictEqual(adminAssignmentLabel('Valheim'), 'Valheim');
  },
  'a group loses the prefix it is stored under'() {
    // `group:` is what the bot compares; it is not a name anybody typed.
    assert.ok(!adminAssignmentLabel('group:Gameserver').includes('group:'),
      adminAssignmentLabel('group:Gameserver'));
    assert.ok(adminAssignmentLabel('group:Gameserver').includes('Gameserver'));
  },
  'and is marked as a group'() {
    assert.notStrictEqual(adminAssignmentLabel('group:Gameserver'), 'Gameserver');
  },
  'a container whose name merely contains the word is untouched'() {
    // "mygroup:thing" is not a group; only the prefix makes one.
    assert.strictEqual(adminAssignmentLabel('mygroup:thing'), 'mygroup:thing');
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
