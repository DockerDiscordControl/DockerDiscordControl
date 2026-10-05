// Runs app/static/js/advanced_settings_modal.js in node: does "Validate key"
// ask the server, and say what the server says? Called from
// tests/spec/test_the_donation_key_is_checked_by_the_server.py.
//
// THE FINDING (operator's question, 2026-10-05: "does this work 100 %?"): the
// button checked a copy of the key list kept in this file. It held five of the
// server's six keys, so the Abyss special edition key was called invalid here
// and accepted by the save; and it logged the valid keys to the console.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

function harness(answer) {
  const asked = [];
  const status = { textContent: '', className: '' };
  const input = { value: '' };
  const byId = { donation_disable_key: input, keyStatus: status };
  const logged = [];
  const sandbox = {
    console: { log: (...a) => logged.push(a.join(' ')), error: (...a) => logged.push(a.join(' ')),
               warn() {} },
    setTimeout() {},
    document: {
      getElementById: (id) => byId[id] || null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    fetch: (url, options) => {
      asked.push({ url, body: JSON.parse(options.body) });
      if (answer instanceof Error) return Promise.reject(answer);
      return Promise.resolve({ ok: answer.ok !== false, status: answer.status || 200,
                               json: () => Promise.resolve(answer.body) });
    },
    t: (key) => key,
    showNotification() {},
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
    'advanced_settings_modal.js'), 'utf8'), sandbox);
  return { sandbox, asked, status, input, logged };
}

const cases = {
  async 'a key the server accepts is called valid'() {
    const h = harness({ body: { success: true, valid: true } });
    h.input.value = '  DDC-ABYSS-whatever  ';
    await h.sandbox.validateDonationKey();
    assert.deepStrictEqual(h.asked.map(a => [a.url, a.body.key]),
      [['/api/donation-key/check', 'DDC-ABYSS-whatever']]);
    assert.ok(h.status.textContent.includes('web.advanced.key_validated'), h.status.textContent);
  },

  async 'a key the server refuses is called invalid'() {
    const h = harness({ body: { success: true, valid: false } });
    h.input.value = 'nonsense';
    await h.sandbox.validateDonationKey();
    assert.ok(h.status.textContent.includes('web.advanced.key_invalid_purchase'), h.status.textContent);
  },

  async 'an unreachable server is not called an invalid key'() {
    const h = harness(new Error('offline'));
    h.input.value = 'DDC-PRO-x';
    await h.sandbox.validateDonationKey();
    assert.ok(h.status.textContent.includes('web.advanced.key_check_failed'), h.status.textContent);
  },

  async 'saving the settings writes no key to the console'() {
    // saveAdvancedSettings printed the key and every copied value (2026-10-05)
    const h = harness({ body: { success: true, valid: true } });
    const key = { name: 'donation_disable_key', value: 'DDC-SECRET-SAVED', type: 'text' };
    const form = { querySelector: () => null, appendChild() {} };
    const modal = { querySelectorAll: () => [key], querySelector: () => key };
    h.sandbox.document.getElementById = (id) =>
      ({ 'config-form': form, advancedSettingsModal: modal }[id] || null);
    h.sandbox.document.createElement = () => ({});
    h.sandbox.saveAdvancedSettings();
    assert.ok(!h.logged.some(line => line.includes('DDC-')), h.logged.join('\n'));
  },

  async 'nothing about a key reaches the console'() {
    const h = harness({ body: { success: true, valid: true } });
    h.input.value = 'DDC-SECRET-TYPED';
    h.sandbox.updateKeyStatus();
    await h.sandbox.validateDonationKey();
    assert.ok(!h.logged.some(line => line.includes('DDC-')), h.logged.join('\n'));
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
