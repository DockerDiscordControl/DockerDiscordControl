// Runs the pure part of app/static/js/backup_restore.js in node: what the
// panel SAYS about a backup and about a refusal. Called from
// tests/spec/test_backup_and_restore_ask_for_the_password_again.py.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'backup_restore.js'), 'utf8'), sandbox);
const { describeBackup, backupErrorText } = sandbox;
const t = key => ({
  'web.backup.preview_text': '{date} {version}: {containers}c {tasks}t {rules}r {groups}g',
  'web.backup.refused': 'refused: {reason}',
}[key] || key);

const cases = {
  'a preview names what is inside'() {
    const text = describeBackup({ created_at: '2026-09-26T18:00:00Z', ddc_version: '3.0.0',
      summary: { containers: 8, tasks: 4, rules: 3, groups: 1 } }, t);
    assert.strictEqual(text, '2026-09-26T18:00:00Z 3.0.0: 8c 4t 3r 1g');
  },
  'a missing summary reads as zero, not undefined'() {
    assert.ok(!describeBackup({}, t).includes('undefined'), describeBackup({}, t));
  },
  'a wrong password and a brake have their own words'() {
    assert.strictEqual(backupErrorText(403, null, t), 'web.backup.wrong_password');
    assert.strictEqual(backupErrorText(429, null, t), 'web.backup.rate_limited');
  },
  'a refused file says why'() {
    assert.strictEqual(backupErrorText(400, { error: 'refused', reason: 'no manifest' }, t),
      'refused: no manifest');
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
