// Runs renderAdminContainers of app/static/js/config-ui.js in node: a group
// name with an apostrophe must not break - or rewrite - the checkbox handler.
// Called from tests/spec/test_an_apostrophe_in_a_group_name_is_just_a_letter.py.
//
// THE FINDING (audit 2026-09-26): the handler was built as
//   onchange="toggleAdminContainer('<id>', '<escapeHtml(name)>', this.checked)"
// HTML-escaping turns ' into &#039; - and the HTML parser turns it back into '
// BEFORE the JavaScript runs. So "Bob's" ended the string early (a syntax
// error: the box could not be toggled), and a name like  x',alert(1),'  ran
// script. Group names may hold anything but / \ and line breaks.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const source = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'config-ui.js'), 'utf8');
function take(name) {
  const start = source.indexOf('function ' + name + '(');
  assert.ok(start > -1, name + ' is gone');
  // To the brace that closes it: what follows may be page code that needs a DOM.
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i += 1) {
    if (source[i] === '{') { depth += 1; }
    if (source[i] === '}') { depth -= 1; if (depth === 0) { return source.slice(start, i + 1); } }
  }
  throw new Error(name + ' never closes');
}

// What the browser does with an attribute value before anything reads it.
function decode(text) {
  return text.replace(/&#0*39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

function render(names) {
  const sandbox = { console, t: key => key, availableContainers: names };
  vm.createContext(sandbox);
  vm.runInContext(['escapeHtmlConfigUI', 'adminAssignmentLabel', 'renderAdminContainers']
    .map(take).join('\n'), sandbox);
  return sandbox.renderAdminContainers('123456789012345678', []);
}

function boxes(html) {
  const found = [];
  const re = /<input\b([^>]*)>/g;
  let match;
  while ((match = re.exec(html)) !== null) {
    const attrs = {};
    const attrRe = /([a-z-]+)="([^"]*)"/g;
    let a;
    while ((a = attrRe.exec(match[1])) !== null) { attrs[a[1]] = decode(a[2]); }
    found.push(attrs);
  }
  // The container boxes only: the first box of each admin is "all containers".
  return found.filter(attrs => !/Unscoped/.test(attrs.onchange || ''));
}

const cases = {
  "an apostrophe leaves the handler valid JavaScript"() {
    const [box] = boxes(render(["group:Bob's"]));
    assert.ok(box.onchange, 'no handler');
    assert.doesNotThrow(() => new Function(box.onchange), box.onchange);
  },
  'a crafted name cannot add a call'() {
    const [box] = boxes(render(["group:x',alert(1),'"]));
    assert.ok(!box.onchange.includes('alert'), box.onchange);
  },
  'the name reaches the handler as it is'() {
    const name = "group:Bob's \"best\" <servers> & co";
    const [box] = boxes(render([name]));
    assert.strictEqual(box['data-name'], name);
    assert.strictEqual(box['data-admin'], '123456789012345678');
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
