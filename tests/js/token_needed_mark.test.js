// Runs app/static/js/config-ui.js in node: when the Info button glows because a
// token protocol has no token, the opened dialog says so at its top and marks
// the token field; a token typed in, or a protocol without one, clears both.
// Called from tests/spec/test_the_dialog_says_what_the_glow_asks_for.py.
//
// THE OPERATOR (2026-10-04): Satisfactory's Info button glowed, "but when I
// click it I do not know why" - the dialog should say what to configure, and
// the option should be marked.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

function classes() {
  const set = new Set();
  return { add: c => set.add(c), remove: c => set.delete(c), contains: c => set.has(c),
           toggle: (c, on) => (on ? set.add(c) : set.delete(c)) };
}

function page({ enabled, protocol, token }) {
  const listeners = {};
  const element = extra => Object.assign({ style: {}, dataset: {}, classList: classes(), textContent: '',
    addEventListener(type, handler) { (listeners[type] = listeners[type] || []).push({ el: this, handler }); } }, extra);
  const ids = {
    'modal-container-name': element({ value: 'Satisfactory' }),
    'modal-query-protocol': element({ value: protocol }),
    'modal-query-token': element({ value: '' }),
    'modal-query-token-wrap': element({ dataset: { labelSatisfactory: 'Satisfactory app token',
                                                   labelPalworld: 'Palworld admin password' } }),
    'modal-query-token-label': element(),
    'modal-query-token-help': element(),
    'modal-query-needs-config': element({ style: { display: 'none' } }),
    'modal-query-needs-config-text': element({ dataset: { template: 'Missing for the player count: {field}' } }),
    'docker-container-list': element({ dispatchEvent() {} }),
  };
  const hidden = {
    'input[name="query_protocol_Satisfactory"]': { value: protocol },
    'input[name="query_token_Satisfactory"]': { value: token },
    '.query-enabled-checkbox[data-container="Satisfactory"]': { checked: enabled },
  };
  const document = {
    addEventListener() {},
    getElementById: id => ids[id] || null,
    querySelector: selector => hidden[selector] || null,
    querySelectorAll: () => [],
    createElement: () => element(),
    createTextNode: text => text,
    body: { appendChild() {} },
  };
  const sandbox = { document, console, setTimeout() {}, t: key => key, Event: function (type) { this.type = type; } };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
    'config-ui.js'), 'utf8'), sandbox);
  const fire = (id, type) => (listeners[type] || []).filter(l => l.el === ids[id]).forEach(l => l.handler());
  return { sandbox, ids, fire };
}

const shown = ids => ids['modal-query-needs-config'].style.display !== 'none';
const marked = ids => ids['modal-query-token'].classList.contains('query-token-needs-config');

const cases = {
  'a glowing container opens with the hint and the marked field'() {
    const { sandbox, ids } = page({ enabled: true, protocol: 'satisfactory', token: '' });
    sandbox.openContainerInfoModal('Satisfactory');
    assert.ok(shown(ids), 'no hint');
    assert.ok(marked(ids), 'the token field is not marked');
    assert.ok(ids['modal-query-needs-config-text'].textContent.includes('Satisfactory app token'),
      ids['modal-query-needs-config-text'].textContent);
  },
  'a token typed in clears both'() {
    const { sandbox, ids } = page({ enabled: true, protocol: 'satisfactory', token: '' });
    sandbox.openContainerInfoModal('Satisfactory');
    sandbox.updateTokenNeededMark();
    ids['modal-query-token'].value = 'abc';
    sandbox.updateTokenNeededMark();
    assert.ok(!shown(ids) && !marked(ids));
  },
  'a container with a token, or with the player count off, shows nothing'() {
    for (const setup of [{ enabled: true, protocol: 'satisfactory', token: 'set' },
                         { enabled: false, protocol: 'satisfactory', token: '' },
                         { enabled: true, protocol: 'source', token: '' }]) {
      const { sandbox, ids } = page(setup);
      sandbox.openContainerInfoModal('Satisfactory');
      assert.ok(!shown(ids) && !marked(ids), JSON.stringify(setup));
    }
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
