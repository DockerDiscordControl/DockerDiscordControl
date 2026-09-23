// Runs app/static/js/container_groups.js in node: what the groups section
// shows. Called from tests/spec/test_the_panel_shows_container_groups.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'container_groups.js'), 'utf8'), sandbox);
const { groupWarning, canSaveGroup, replacementWarning } = sandbox;

const TEXTS = { missing: 'Not found any more: {names}', empty: 'No containers yet' };

const cases = {
  'a group that lost a container says which one'() {
    const warning = groupWarning({ containers: ['Valheim', 'Enshrouded'], missing: ['Enshrouded'] }, TEXTS);
    assert.strictEqual(warning.level, 'warning');
    assert.ok(warning.text.includes('Enshrouded'), warning.text);
  },
  'a complete group says nothing'() {
    assert.strictEqual(groupWarning({ containers: ['Valheim'], missing: [] }, TEXTS), null);
  },
  'an empty group is marked, because it does nothing'() {
    const warning = groupWarning({ containers: [], missing: [] }, TEXTS);
    assert.strictEqual(warning.level, 'info');
  },
  'a group without a name cannot be saved'() {
    assert.strictEqual(canSaveGroup('   ', ['Valheim']), false);
    assert.strictEqual(canSaveGroup('', []), false);
    assert.strictEqual(canSaveGroup('Gameserver', []), true);
  },
  'a name longer than the service accepts is refused here too'() {
    assert.strictEqual(canSaveGroup('x'.repeat(81), []), false);
    assert.strictEqual(canSaveGroup('x'.repeat(80), []), true);
  },
  'typing the name of an existing group warns that it is replaced'() {
    // THE FINDING: saving replaces the members. Adding one container to a
    // group of seven this way left a group of one, with a green "Saved".
    const groups = [{ name: 'Gameserver', containers: ['a', 'b', 'c'] }];
    const warning = replacementWarning('gameserver', groups, false,
                                       { replace: '{name} has {count} containers' });
    assert.ok(warning && warning.includes('Gameserver'), warning);
    assert.ok(warning.includes('3'), warning);
  },
  'editing a group that was loaded into the form does not warn'() {
    const groups = [{ name: 'Gameserver', containers: ['a'] }];
    assert.strictEqual(replacementWarning('Gameserver', groups, true, { replace: 'x' }), null);
  },
  'a new name does not warn'() {
    const groups = [{ name: 'Gameserver', containers: ['a'] }];
    assert.strictEqual(replacementWarning('Infrastruktur', groups, false, { replace: 'x' }), null);
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
