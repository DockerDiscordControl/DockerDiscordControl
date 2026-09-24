// Runs app/static/js/form_scope.js in node: what counts as an unsaved change
// to the settings form. Called from
// tests/spec/test_a_self_saving_control_raises_no_unsaved_warning.py.
//
// THE FINDING (operator, 2026-09-24): the debug switch saves itself, and the
// form still warned about unsaved changes - because the log view had moved
// inside #config-form and the form reports everything inside it. The listener's
// exceptions were three hard-coded ids, so the fourth control that did not
// belong to the save was simply not on the list.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'form_scope.js'), 'utf8'), sandbox);
const { belongsToTheFormSave } = sandbox;

// A stand-in for a DOM element: closest() answers from a list of selectors the
// element is considered to be inside.
const element = (id, inside = []) => ({
  id,
  closest(selector) {
    return inside.includes(selector) ? { tag: selector } : null;
  },
});

const cases = {
  'an ordinary field is part of the save'() {
    assert.strictEqual(belongsToTheFormSave(element('bot_token')), true);
  },
  'a control that saves itself is not'() {
    // THE FINDING: the debug switch, which posts on change.
    assert.strictEqual(
      belongsToTheFormSave(element('debugLevelToggle', ['[data-saves-itself="true"]'])), false);
  },
  'the task status filter is not'() {
    assert.strictEqual(belongsToTheFormSave(element('taskFilterStatus')), false);
  },
  'anything inside the task list is not'() {
    // Nine of these were spread across three listeners in two lists that had
    // drifted apart - the change listener knew three, the click listener six.
    for (const where of ['#taskListBody', '.task-filters', '.editTaskBtn',
                         '.deleteTaskBtn', '.toggle-active']) {
      assert.strictEqual(belongsToTheFormSave(element('x', [where])), false, where);
    }
    assert.strictEqual(belongsToTheFormSave(element('refreshTasksBtn')), false);
  },
  'nothing at all is not a change'() {
    assert.strictEqual(belongsToTheFormSave(null), false);
    assert.strictEqual(belongsToTheFormSave(undefined), false);
  },
  'something without closest() does not throw'() {
    // Events can carry targets that are not elements - a document, a window.
    assert.strictEqual(belongsToTheFormSave({ id: 'odd' }), false);
  },
  'a field merely NEAR a self-saving control still counts'() {
    // closest() walks up, so only a field inside the marked region is
    // excluded. Without this the marker could quietly switch off the warning
    // for half the form.
    assert.strictEqual(belongsToTheFormSave(element('language', [])), true);
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
