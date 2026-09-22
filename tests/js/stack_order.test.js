// Runs app/static/js/stack_order.js in node: the "sort by stack" button of the
// server order. Called from
// tests/spec/test_the_server_order_can_be_sorted_by_stack.py (needs node).
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

function load(document) {
  const sandbox = { document, console };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  const file = path.join(__dirname, '..', '..', 'app', 'static', 'js', 'stack_order.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), sandbox, { filename: file });
  return sandbox;
}

const noDom = { addEventListener() {}, getElementById: () => null };
const e = (name, project) => ({ name, project });

const cases = {
  'a stack gathers where its first member stands'() {
    const { stackOrder } = load(noDom);
    const order = stackOrder([e('db', 'blog'), e('plex', null), e('web', 'blog'),
      e('grafana', 'mon'), e('cache', 'blog'), e('prom', 'mon')]);
    assert.deepStrictEqual(Array.from(order), ['db', 'web', 'cache', 'plex', 'grafana', 'prom']);
  },
  'containers outside a stack keep their place among each other'() {
    const { stackOrder } = load(noDom);
    const order = stackOrder([e('a', null), e('b', null), e('x1', 's'), e('c', ''), e('x2', 's')]);
    assert.deepStrictEqual(Array.from(order), ['a', 'b', 'x1', 'x2', 'c']);
  },
  'sorting twice changes nothing more'() {
    const { stackOrder } = load(noDom);
    const once = Array.from(stackOrder([e('db', 'blog'), e('plex', null), e('web', 'blog')]));
    const byName = { db: 'blog', plex: null, web: 'blog' };
    const twice = Array.from(stackOrder(once.map(n => e(n, byName[n]))));
    assert.deepStrictEqual(twice, once);
  },
  'the button reorders the table rows and renumbers them'() {
    const rows = [['db', 'blog'], ['plex', ''], ['web', 'blog']].map(([name, project]) => ({
      name, project,
      getAttribute(attr) {
        return attr === 'data-container-name' ? name : attr === 'data-compose-project' ? project : null;
      },
    }));
    const tbody = {
      rows: rows.slice(),
      querySelectorAll() { return this.rows.slice(); },
      appendChild(row) { this.rows = this.rows.filter(r => r !== row).concat([row]); },
    };
    const document = { addEventListener() {}, getElementById: id => (id === 'docker-container-list' ? tbody : null) };
    const sandbox = load(document);
    const calls = [];
    sandbox.updateOrderNumbers = () => calls.push('numbers');
    sandbox.updateMoveButtons = () => calls.push('buttons');
    sandbox.markConfigurationChanged = () => calls.push('changed');
    assert.strictEqual(sandbox.sortServerRowsByStack(), true);
    assert.deepStrictEqual(tbody.rows.map(r => r.name), ['db', 'web', 'plex']);
    assert.deepStrictEqual(calls, ['numbers', 'buttons', 'changed']);
    calls.length = 0;
    assert.strictEqual(sandbox.sortServerRowsByStack(), false, 'already sorted - nothing changed');
    assert.deepStrictEqual(calls, []);
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(cases)) {
  try { fn(); console.log(`ok     ${name}`); } catch (err) { failed++; console.log(`FAILED ${name}\n${err.stack}`); }
}
process.exit(failed ? 1 : 0);
