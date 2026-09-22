// Runs app/static/js/progress_bars.js in node: the width of a progress bar when
// the server could not measure its maximum. Called from
// tests/spec/test_an_unknown_maximum_is_not_a_full_bar.py (needs node).
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'progress_bars.js'), 'utf8'), sandbox);
const { barWidth } = sandbox;

const cases = {
  'an ordinary measurement is a percentage'() {
    assert.strictEqual(barWidth(5, 10), 50);
  },
  'a maximum the server could not measure is not a full bar'() {
    // THE FINDING: null as the maximum made 5/null === Infinity, and
    // Math.min(100, Infinity) === 100 - a full bar out of no data at all.
    assert.strictEqual(barWidth(5, null), null);
    assert.strictEqual(barWidth(5, undefined), null);
  },
  'a maximum of zero is not a full bar either'() {
    assert.strictEqual(barWidth(5, 0), null);
  },
  'a missing current value is unknown too'() {
    assert.strictEqual(barWidth(null, 10), null);
  },
  'more than the maximum is still capped'() {
    assert.strictEqual(barWidth(15, 10), 100);
  },
  'zero progress is zero, not unknown'() {
    assert.strictEqual(barWidth(0, 10), 0);
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(cases)) {
  try { fn(); console.log(`ok     ${name}`); } catch (err) { failed++; console.log(`FAILED ${name}\n${err.stack}`); }
}
process.exit(failed ? 1 : 0);
