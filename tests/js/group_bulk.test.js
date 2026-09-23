// Runs app/static/js/group_bulk.js in node: applying a group to the container
// table. Called from tests/spec/test_the_container_table_can_act_on_a_group.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'group_bulk.js'), 'utf8'), sandbox);
const { bulkPlan, bulkMessage } = sandbox;

const TEXTS = {
  applied: '{count} container(s) updated.',
  not_on_page: 'Not in the table: {names}',
  nothing: 'This group has no container this page shows.',
  pick_group: 'Pick a group first.'
};

const cases = {
  'the plan names the rows the group has on this page'() {
    const plan = bulkPlan(['Valheim', 'Icarus'], ['Icarus', 'Valheim', 'Enshrouded']);
    assert.deepStrictEqual(plan.rows.sort(), ['Icarus', 'Valheim']);
    assert.deepStrictEqual(plan.missing, []);
  },
  'a container the table does not show is reported, not skipped'() {
    // THE POINT: the group is resolved against the containers DDC steers; the
    // table lists what the host has. A container in the group but not on the
    // page is one the operator has to hear about - otherwise "apply to group"
    // silently acts on five of seven.
    const plan = bulkPlan(['Valheim', 'Gone'], ['Valheim']);
    assert.deepStrictEqual(plan.rows, ['Valheim']);
    assert.deepStrictEqual(plan.missing, ['Gone']);
  },
  'a group with nothing on this page plans nothing'() {
    const plan = bulkPlan(['Gone', 'AlsoGone'], ['Valheim']);
    assert.deepStrictEqual(plan.rows, []);
    assert.deepStrictEqual(plan.missing.sort(), ['AlsoGone', 'Gone']);
  },
  'no group picked is not an empty group'() {
    const plan = bulkPlan(null, ['Valheim']);
    assert.strictEqual(plan.rows.length, 0);
    assert.strictEqual(plan.chosen, false);
  },
  'the message counts what was changed'() {
    const message = bulkMessage({ rows: ['a', 'b'], missing: [], chosen: true }, TEXTS);
    assert.strictEqual(message.level, 'success');
    assert.ok(message.text.includes('2'), message.text);
  },
  'the message names the containers that were not there'() {
    const message = bulkMessage({ rows: ['a'], missing: ['Gone'], chosen: true }, TEXTS);
    assert.strictEqual(message.level, 'warning');
    assert.ok(message.text.includes('Gone'), message.text);
    assert.ok(message.text.includes('1'), message.text);
  },
  'a group that changed nothing does not say success'() {
    const message = bulkMessage({ rows: [], missing: ['Gone'], chosen: true }, TEXTS);
    assert.strictEqual(message.level, 'warning');
    assert.ok(message.text.includes('Gone'), message.text);
  },
  'no group picked asks for one'() {
    const message = bulkMessage({ rows: [], missing: [], chosen: false }, TEXTS);
    assert.strictEqual(message.level, 'info');
    assert.strictEqual(message.text, TEXTS.pick_group);
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
