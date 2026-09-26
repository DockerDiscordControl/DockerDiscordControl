// Runs app/static/js/timezone_question.js in node: after a save that changed
// the panel timezone, the operator is asked whether existing tasks move along.
// Called from tests/spec/test_changing_the_panel_timezone_asks_about_the_tasks.py.
//
// THE FINDING (audit 2026-09-26): the question lived only in main.js, a file
// no template loads. The live save handler (panel.js saveConfigAjax) ignored
// data.timezone_question, so the question was computed and never asked.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
  'timezone_question.js'), 'utf8'), sandbox);
const { askAboutTaskTimezone } = sandbox;

const QUESTION = { tasks: 3, old: 'Europe/Berlin', new: 'America/New_York' };

function world(answer, reply = { success: true, moved: 3 }) {
  const seen = { asked: [], posted: [] };
  return {
    seen,
    deps: {
      confirm: text => { seen.asked.push(text); return answer; },
      fetch: async (url, init) => {
        seen.posted.push({ url, init });
        return { ok: true, json: async () => reply };
      },
      t: key => ({ 'web.timezone.question_body': '{count} tasks, {old} -> {new}' }[key] || key),
    },
  };
}

const cases = {
  async 'the operator is asked, with the numbers in the words'() {
    const { seen, deps } = world(false);
    await askAboutTaskTimezone(QUESTION, deps);
    assert.strictEqual(seen.asked.length, 1);
    assert.ok(seen.asked[0].includes('3 tasks, Europe/Berlin -> America/New_York'), seen.asked[0]);
  },
  async 'yes moves the tasks to the NEW zone'() {
    const { seen, deps } = world(true);
    const moved = await askAboutTaskTimezone(QUESTION, deps);
    assert.strictEqual(seen.posted.length, 1);
    assert.strictEqual(seen.posted[0].url, '/tasks/retime');
    assert.strictEqual(seen.posted[0].init.method, 'POST');
    assert.deepStrictEqual(JSON.parse(seen.posted[0].init.body), { timezone: 'America/New_York' });
    assert.strictEqual(moved, 3);
  },
  async 'no leaves the tasks alone'() {
    const { seen, deps } = world(false);
    const moved = await askAboutTaskTimezone(QUESTION, deps);
    assert.strictEqual(seen.posted.length, 0);
    assert.strictEqual(moved, 0);
  },
  async 'no question, nothing asked'() {
    const { seen, deps } = world(true);
    await askAboutTaskTimezone(null, deps);
    await askAboutTaskTimezone(undefined, deps);
    assert.strictEqual(seen.asked.length + seen.posted.length, 0);
  },
  async 'a refused move is not reported as moved'() {
    const { deps } = world(true, { success: false, error: 'x' });
    assert.strictEqual(await askAboutTaskTimezone(QUESTION, deps), -1);
  },
};

(async () => {
  let failed = 0;
  for (const [name, run] of Object.entries(cases)) {
    try {
      await run();
      console.log('ok   - ' + name);
    } catch (e) {
      failed += 1;
      console.log('FAIL - ' + name + ': ' + e.message);
    }
  }
  process.exit(failed === 0 ? 0 : 1);
})();
