// Runs app/static/js/rule_targets.js in node: which target checkboxes the rule
// editor shows. Called from tests/spec/test_a_rule_does_not_widen_itself.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'rule_targets.js'), 'utf8'), sandbox);
const { targetCheckboxes, saveWidensToEveryContainer } = sandbox;

const GROUPS = [{ name: 'Gameserver', containers: ['Valheim', 'alpha'] }];
const CONTAINERS = ['Valheim', 'alpha', 'AdGuard-Home'];

const cases = {
  'a group the rule watches is ticked'() {
    const boxes = targetCheckboxes(GROUPS, CONTAINERS, ['group:Gameserver']);
    const group = boxes.find(b => b.value === 'group:Gameserver');
    assert.strictEqual(group.checked, true);
    assert.strictEqual(group.kind, 'group');
    assert.strictEqual(group.count, 2);
  },
  'a group that no longer exists is KEPT, ticked and marked'() {
    // THE FINDING: without this the tick is lost, the rule saves an empty
    // trigger list, and DDC reads that as "every container".
    const boxes = targetCheckboxes(GROUPS, CONTAINERS, ['group:Gone']);
    const gone = boxes.find(b => b.value === 'group:Gone');
    assert.ok(gone, 'the deleted group vanished from the editor');
    assert.strictEqual(gone.checked, true);
    assert.strictEqual(gone.missing, true);
    assert.strictEqual(gone.label, 'Gone');
  },
  'a container that is no longer configured is kept too'() {
    const boxes = targetCheckboxes(GROUPS, CONTAINERS, ['deleted-container']);
    const gone = boxes.find(b => b.value === 'deleted-container');
    assert.strictEqual(gone.checked, true);
    assert.strictEqual(gone.missing, true);
    assert.strictEqual(gone.kind, 'container');
  },
  'nothing is offered twice'() {
    const boxes = targetCheckboxes(GROUPS, CONTAINERS, ['Valheim', 'group:Gameserver']);
    const values = boxes.map(b => b.value);
    assert.strictEqual(new Set(values).size, values.length, values.join(','));
  },
  'groups come before containers'() {
    const boxes = targetCheckboxes(GROUPS, CONTAINERS, []);
    assert.strictEqual(boxes[0].kind, 'group');
    assert.strictEqual(boxes[1].kind, 'container');
  },
  'emptying a watching rule is flagged as widening'() {
    assert.strictEqual(saveWidensToEveryContainer(true, [], ['group:Gameserver']), true);
  },
  'a rule that watched everything already is not flagged'() {
    assert.strictEqual(saveWidensToEveryContainer(true, [], []), false);
  },
  'a message rule is not flagged - its empty list means something else'() {
    assert.strictEqual(saveWidensToEveryContainer(false, [], ['Valheim']), false);
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
