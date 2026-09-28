// Runs app/static/js/player_options.js in node: the three player-option fields
// of the task form, the task edit dialog and the rule editor (v3.0.2). Called
// from tests/spec/test_the_player_options_fields_say_what_they_hold.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

// A page with the fields of one prefix; values set per case.
function page(prefix, values) {
  const fields = {
    [prefix + 'PlayerGate']: { hidden: true },
    [prefix + 'WaitEmpty']: { checked: !!values.wait },
    [prefix + 'MaxWait']: { value: values.maxWait === undefined ? '120' : String(values.maxWait) },
    [prefix + 'WarnMinutes']: { value: values.warn === undefined ? '0' : String(values.warn) },
  };
  const sandbox = { console, document: { getElementById: (id) => fields[id] || null } };
  // The table each caller holds (task_form.js, tasks.js, auto_actions.js)
  sandbox.F = { PlayerGate: prefix + 'PlayerGate', WaitEmpty: prefix + 'WaitEmpty',
                MaxWait: prefix + 'MaxWait', WarnMinutes: prefix + 'WarnMinutes' };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
    'player_options.js'), 'utf8'), sandbox);
  return { sandbox, fields, F: sandbox.F };
}

const cases = {
  'nothing switched on sends nothing'() {
    const { sandbox, F } = page('task', {});
    assert.deepStrictEqual({ ...sandbox.readPlayerOptions(F, 'restart') }, {});
  },
  'waiting sends its minutes, the warning its own'() {
    const { sandbox, F } = page('task', { wait: true, maxWait: 60, warn: 10 });
    assert.deepStrictEqual({ ...sandbox.readPlayerOptions(F, 'restart') },
      { wait_for_empty: true, max_wait_minutes: 60, warn_minutes: 10 });
  },
  'a start sends no options, whatever the fields hold'() {
    const { sandbox, F } = page('task', { wait: true, warn: 10 });
    assert.deepStrictEqual({ ...sandbox.readPlayerOptions(F, 'start') }, {});
  },
  'the block is shown for restart and stop only'() {
    const { sandbox, fields, F } = page('editTask', {});
    sandbox.showPlayerOptions(F, 'stop');
    assert.strictEqual(fields.editTaskPlayerGate.hidden, false);
    sandbox.showPlayerOptions(F, 'start');
    assert.strictEqual(fields.editTaskPlayerGate.hidden, true);
  },
  'editing fills the fields, and an empty option set clears them'() {
    const { sandbox, fields, F } = page('editTask', { wait: true, maxWait: 30, warn: 5 });
    sandbox.fillPlayerOptions(F, { wait_for_empty: true, max_wait_minutes: 240, warn_minutes: 15 });
    assert.strictEqual(fields.editTaskMaxWait.value, 240);
    sandbox.fillPlayerOptions(F, {});
    assert.strictEqual(fields.editTaskWaitEmpty.checked, false);
    assert.strictEqual(fields.editTaskWarnMinutes.value, 0);
  },
  'rule types map to the task words'() {
    const { sandbox, F } = page('aasRule', {});
    assert.strictEqual(sandbox.playerGateActionOf('RECREATE'), 'restart');
    assert.strictEqual(sandbox.playerGateActionOf('STOP'), 'stop');
    assert.strictEqual(sandbox.playerGateActionOf('NOTIFY'), '');
  },
  'the task list line names both options'() {
    const { sandbox, F } = page('task', {});
    const line = sandbox.describePlayerOptions({ wait_for_empty: true, max_wait_minutes: 120, warn_minutes: 10 },
      { whenEmpty: 'only when empty (at most {minutes} min)', warning: 'warning {minutes} min before' });
    assert.strictEqual(line, 'only when empty (at most 120 min) · warning 10 min before');
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
