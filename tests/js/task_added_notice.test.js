// Runs app/static/js/task_added_notice.js in node: what the task form shows
// after a 201. Called from
// tests/spec/test_a_task_in_the_past_is_not_called_added.py (needs node).
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'task_added_notice.js'), 'utf8'), sandbox);
const { taskAddedNotice } = sandbox;

const ADDED = 'Task added';

const cases = {
  'a task that was switched off is a warning, in the server\'s words'() {
    // THE FINDING: a one-time task in the past is saved and switched off, and
    // the form printed its own green "Task added" all the same.
    const notice = taskAddedNotice({
      message: 'Task added, but switched off: the time given is in the past.',
      task: { id: 'a', is_active: false },
    }, ADDED);
    assert.strictEqual(notice.level, 'alert-warning');
    assert.ok(notice.text.includes('switched off'), notice.text);
  },
  'an ordinary task keeps the green line'() {
    const notice = taskAddedNotice({ message: 'Task added successfully',
                                     task: { id: 'a', is_active: true } }, ADDED);
    assert.strictEqual(notice.level, 'alert-success');
    assert.ok(notice.text.startsWith(ADDED), notice.text);
  },
  'a body without a task is not treated as switched off'() {
    assert.strictEqual(taskAddedNotice({}, ADDED).level, 'alert-success');
    assert.strictEqual(taskAddedNotice(null, ADDED).level, 'alert-success');
  },
  'a warning without a message falls back to the page\'s own text'() {
    const notice = taskAddedNotice({ task: { is_active: false } }, ADDED);
    assert.strictEqual(notice.text, ADDED);
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
