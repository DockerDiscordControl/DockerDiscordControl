// Runs app/static/js/paging.js in node: how a long list is cut into pages.
// Called from tests/spec/test_long_lists_are_paged_not_scrolled.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'paging.js'), 'utf8'), sandbox);
const { pageCount, clampPage, pageSlice } = sandbox;

const SEVEN = ['a', 'b', 'c', 'd', 'e', 'f', 'g'];

const cases = {
  'an empty list is still one page'() {
    // Zero pages would mean "page 0 of 0" under the table, and a pager with
    // nothing in it. One empty page is what the operator sees anyway.
    assert.strictEqual(pageCount(0, 7), 1);
    assert.deepStrictEqual(pageSlice([], 1, 7), []);
  },
  'exactly a full page is one page, not two'() {
    assert.strictEqual(pageCount(7, 7), 1);
    assert.deepStrictEqual(pageSlice(SEVEN, 1, 7), SEVEN);
  },
  'one more than a page is two pages'() {
    assert.strictEqual(pageCount(8, 7), 2);
    assert.deepStrictEqual(pageSlice(SEVEN.concat('h'), 2, 7), ['h']);
  },
  'the last page holds the remainder'() {
    const twenty = Array.from({ length: 20 }, (_, i) => i);
    assert.strictEqual(pageCount(20, 7), 3);
    assert.deepStrictEqual(pageSlice(twenty, 3, 7), [14, 15, 16, 17, 18, 19]);
  },
  'a page past the end comes back to the last one'() {
    // THE CASE THAT BITES: the operator is on page 4, types three letters into
    // the search, and there are now five matches. Without this he stares at an
    // empty table and no message, because page 4 of 1 is nothing at all.
    assert.strictEqual(clampPage(4, 5, 7), 1);
    assert.deepStrictEqual(pageSlice(['x', 'y'], 9, 7), ['x', 'y']);
  },
  'a page before the first comes back to it'() {
    assert.strictEqual(clampPage(0, 20, 7), 1);
    assert.strictEqual(clampPage(-3, 20, 7), 1);
  },
  'a page in the middle is left alone'() {
    assert.strictEqual(clampPage(2, 20, 7), 2);
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
