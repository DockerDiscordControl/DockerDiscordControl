// Runs app/static/js/escape.js in node: what ddcEscapeHtml() does to text
// that did not come from this page. Called from
// tests/spec/test_no_page_parses_foreign_text_as_markup.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'escape.js'), 'utf8'), sandbox);
const { ddcEscapeHtml } = sandbox;

const cases = {
  'a tag becomes text'() {
    assert.strictEqual(ddcEscapeHtml('<img src=x onerror=alert(1)>'),
      '&lt;img src=x onerror=alert(1)&gt;');
  },
  'both quotes go, because the result may land in an attribute'() {
    // title="${message}" - one quote there ends the attribute early, which is
    // the whole attack. Neither quote is escaped by a textContent round trip,
    // which is why this is not that trick.
    assert.strictEqual(ddcEscapeHtml(`a"b'c`), 'a&quot;b&#39;c');
  },
  'the ampersand is escaped first, so nothing is escaped twice'() {
    // & after < would turn &lt; into &amp;lt; and print the markup instead of
    // hiding it.
    assert.strictEqual(ddcEscapeHtml('<'), '&lt;');
    assert.strictEqual(ddcEscapeHtml('&lt;'), '&amp;lt;');
  },
  'ordinary text is left alone'() {
    assert.strictEqual(ddcEscapeHtml('Container Valheim could not be stopped'),
      'Container Valheim could not be stopped');
  },
  'nothing at all is an empty string, not "undefined"'() {
    // These are error paths: `Error: ${ddcEscapeHtml(e.message)}` where the
    // exception carried no message must not read "Error: undefined".
    assert.strictEqual(ddcEscapeHtml(undefined), '');
    assert.strictEqual(ddcEscapeHtml(null), '');
    assert.strictEqual(ddcEscapeHtml(0), '0');
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
