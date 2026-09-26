// Runs the pure part of app/static/js/maintenance.js in node: how one pause
// is written in the panel's list. Called from
// tests/spec/test_maintenance_is_set_from_the_panel_and_from_discord.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'maintenance.js'), 'utf8'), sandbox);
const { maintenanceEntry } = sandbox;
const t = key => ({ 'web.maintenance.until': '{container} until {time}' }[key] || key);

const cases = {
  'a pause names its container and its end'() {
    const text = maintenanceEntry('Valheim', { until: 1790449200 }, t, d => d.toISOString());
    assert.strictEqual(text, 'Valheim until 2026-09-26T19:00:00.000Z');
  },
  'a name with markup stays text (the list uses textContent)'() {
    const text = maintenanceEntry('<b>x</b>', { until: 0 }, t, () => 'then');
    assert.strictEqual(text, '<b>x</b> until then');
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
