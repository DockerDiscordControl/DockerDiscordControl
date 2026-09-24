// Runs app/static/js/restart_notice.js in node: when a save really needs the
// container restarted. Called from
// tests/spec/test_a_restart_is_only_asked_for_when_it_is_needed.py.
//
// THE FINDING (operator, 2026-09-24): the page asked whether a
// .requires-restart field HAS a value, not whether it CHANGED. A bot token is
// never empty, so the notice appeared after every save.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'restart_notice.js'), 'utf8'), sandbox);
const { restartIsNeeded } = sandbox;

const field = (value, initial, extra = {}) =>
  Object.assign({ value, getAttribute: name => (name === 'data-initial-value' ? initial : null) },
    extra);

const cases = {
  'an untouched token asks for nothing'() {
    // THE FINDING: this one used to answer true, because the value is not empty.
    assert.strictEqual(restartIsNeeded([field('abc.def.ghi', 'abc.def.ghi')]), false);
  },
  'a changed token asks for a restart'() {
    assert.strictEqual(restartIsNeeded([field('new.token', 'abc.def.ghi')]), true);
  },
  'one changed field among untouched ones is enough'() {
    assert.strictEqual(restartIsNeeded([
      field('abc', 'abc'), field('99', '11'), field('x', 'x')]), true);
  },
  'nothing at all asks for nothing'() {
    assert.strictEqual(restartIsNeeded([]), false);
    assert.strictEqual(restartIsNeeded(null), false);
    assert.strictEqual(restartIsNeeded(undefined), false);
  },
  'an empty field that was always empty is unchanged'() {
    assert.strictEqual(restartIsNeeded([field('', '')]), false);
  },
  'clearing a field is a change'() {
    assert.strictEqual(restartIsNeeded([field('', 'abc')]), true);
  },
  'a field the page never recorded is not guessed at'() {
    // Without a remembered value there is nothing to compare, and guessing
    // "changed" is how the always-on notice would come back.
    assert.strictEqual(restartIsNeeded([field('abc', null)]), false);
  },
  'a ticked checkbox counts as changed'() {
    assert.strictEqual(restartIsNeeded([
      field('1', '', { type: 'checkbox', checked: true })]), true);
  },
  'an untouched checkbox does not'() {
    assert.strictEqual(restartIsNeeded([
      field('1', '1', { type: 'checkbox', checked: true })]), false);
    assert.strictEqual(restartIsNeeded([
      field('1', '', { type: 'checkbox', checked: false })]), false);
  },
  'numbers and strings are compared as text'() {
    assert.strictEqual(restartIsNeeded([field(30, '30')]), false);
    assert.strictEqual(restartIsNeeded([field(31, '30')]), true);
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
