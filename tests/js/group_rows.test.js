// Runs app/static/js/group_rows.js in node: what a group's permission list
// looks like after a box is ticked or cleared. Called from
// tests/spec/test_a_group_is_a_row_like_a_container.py.
//
// THE RULE THIS PINS (operator, 2026-09-24): a group's permissions are the
// GROUP's. Nothing here reads a container, because nothing about a container
// decides this - the list that goes into groups.json is built from the list
// that came out of it, plus or minus the one box that was clicked.
//
// It replaced a combinedState() that answered "what do this group's containers
// have in common", tri-state and all. That was the design the operator
// rejected: a group drawn as a summary of its members is a group that cannot
// be allowed to do something none of them may do on its own.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'group_rows.js'), 'utf8'), sandbox);
const { withPermission, groupMatches } = sandbox;

// Copied into THIS realm before comparing: an array built inside the vm
// context carries that context's Array prototype, and deepStrictEqual would
// reject it for the prototype rather than for the answer.
const after = (actions, action, checked) =>
  Array.from(withPermission(actions, action, checked));

const cases = {
  'ticking a box adds that action'() {
    assert.deepStrictEqual(after(['status'], 'restart', true), ['status', 'restart']);
  },
  'clearing a box removes it'() {
    assert.deepStrictEqual(after(['status', 'stop', 'restart'], 'stop', false),
      ['status', 'restart']);
  },
  'the order is always the order of the columns'() {
    // The list is written to groups.json and read back into the same four
    // boxes. Stored in click order it would come back shuffled, and a diff of
    // the file would show a change where the operator changed nothing.
    assert.deepStrictEqual(after(['restart', 'status'], 'start', true),
      ['status', 'start', 'restart']);
  },
  'ticking what is already ticked changes nothing'() {
    assert.deepStrictEqual(after(['status', 'stop'], 'stop', true), ['status', 'stop']);
  },
  'clearing what is not there changes nothing'() {
    assert.deepStrictEqual(after(['status'], 'restart', false), ['status']);
  },
  'a group may end up allowed to do nothing'() {
    // Not the same as a group that never said: the service stores the empty
    // list, so a group can be parked without being deleted.
    assert.deepStrictEqual(after(['stop'], 'stop', false), []);
  },
  'an unknown action is not smuggled in'() {
    // The service refuses it, and a refusal that arrives after the tick is
    // already drawn is the worst of both. The four are the four columns.
    assert.deepStrictEqual(after(['status'], 'self_destruct', true), ['status']);
  },
  'a missing list is read as no permissions, not as a crash'() {
    assert.deepStrictEqual(after(undefined, 'status', true), ['status']);
  },

  // --- what the search shows -----------------------------------------------
  'a group matches its own name'() {
    assert.strictEqual(groupMatches({ name: 'Icaruse', containers: [] }, 'icar'), true);
  },
  'a group matches by a container it holds'() {
    // The question an operator has when they type a container name is "where
    // is this thing", and a group holding it is part of the answer.
    assert.strictEqual(groupMatches({ name: 'Gameserver', containers: ['Valheim'] }, 'valh'),
      true);
  },
  'and is hidden when neither matches'() {
    assert.strictEqual(groupMatches({ name: 'Gameserver', containers: ['Valheim'] }, 'zzz'),
      false);
  },
  'an empty search shows every group'() {
    assert.strictEqual(groupMatches({ name: 'Gameserver', containers: [] }, ''), true);
    assert.strictEqual(groupMatches({ name: 'Gameserver', containers: [] }, '   '), true);
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
