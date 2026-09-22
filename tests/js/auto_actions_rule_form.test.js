// Runs app/static/js/auto_actions.js against a small stand-in DOM and checks
// the rule the editor sends to the server. Called from
// tests/spec/test_the_rule_form_keeps_the_trigger_type.py (needs node).
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

function makeEnv() {
  const els = {};
  const ids = ['aasRuleId', 'aasRuleName', 'aasRulePriority', 'aasRuleChannelIds', 'aasRuleUsers',
    'aasRuleRequiredKeywords', 'aasRuleKeywords', 'aasRuleMatchMode', 'aasRuleIgnore', 'aasRuleRegex',
    'aasRuleIsWebhook', 'aasRuleActionType', 'aasRuleDelay', 'aasRuleCooldown', 'aasRuleCooldownScope',
    'aasRuleOnlyRunning', 'aasRuleTriggerType', 'aasRuleRestartThreshold', 'aasRuleRestartWindow',
    'aasMessageTriggerFields', 'aasContainerTriggerFields'];
  for (const id of ids) {
    els[id] = { id, value: '', checked: false, focus() {}, style: {},
      classList: { add() {}, remove() {}, toggle() {} } };
  }
  els.aasRuleMatchMode.value = 'any';
  els.aasRuleActionType.value = 'NOTIFY';
  els.aasRuleCooldownScope.value = 'container';
  els.aasRuleTriggerType.value = 'message';
  const containers = ['web', 'db'].map(value => ({ value, checked: false }));
  const states = ['stopped', 'unhealthy', 'restart_loop'].map(value => ({ value, checked: false }));
  const feedback = [{ value: '', checked: true }, { value: '555', checked: false }];
  const document = {
    getElementById: id => els[id] || null,
    addEventListener() {},
    querySelectorAll(sel) {
      if (sel === '.aas-container-checkbox:checked') return containers.filter(b => b.checked);
      if (sel === '.aas-container-checkbox') return containers;
      if (sel === '.aas-state-checkbox:checked') return states.filter(b => b.checked);
      if (sel === '.aas-state-checkbox') return states;
      if (sel === 'input[name="aasFeedbackChannel"]') return feedback;
      return [];
    },
    querySelector(sel) {
      if (sel === 'input[name="aasFeedbackChannel"]:checked') return feedback.find(f => f.checked) || null;
      return null;
    },
  };
  const sent = [];
  const alerts = [];
  const ctx = {
    document, console, window: {},
    alert: m => alerts.push(m),
    t: k => k,
    fetch: async (url, opts) => {
      sent.push({ url, body: JSON.parse(opts.body) });
      return { json: async () => ({ success: true }) };
    },
    bootstrap: { Modal: { getInstance: () => ({ hide() {} }) } },
    showNotification() {},
  };
  vm.createContext(ctx);
  const source = fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js', 'auto_actions.js'), 'utf8');
  vm.runInContext(source, ctx);
  ctx.loadAASRules = () => {};
  return { ctx, els, containers, states, sent, alerts };
}

const tests = {
  async 'a new container-state rule is sent as one'() {
    const env = makeEnv();
    env.els.aasRuleName.value = 'Watch web';
    env.els.aasRuleTriggerType.value = 'container_state';
    env.states[0].checked = true;  // stopped
    env.states[2].checked = true;  // restart_loop
    env.els.aasRuleRestartThreshold.value = '5';
    env.els.aasRuleRestartWindow.value = '20';
    env.containers[0].checked = true;
    await env.ctx.saveAASRule();
    assert.deepStrictEqual(env.alerts, []);
    const trigger = env.sent[0].body.trigger;
    assert.strictEqual(trigger.type, 'container_state');
    assert.deepStrictEqual(trigger.states, ['stopped', 'restart_loop']);
    assert.deepStrictEqual(trigger.containers, ['web']);
    assert.strictEqual(trigger.restart_threshold, 5);
    assert.strictEqual(trigger.restart_window_minutes, 20);
  },

  async 'no container ticked means every container, not an error'() {
    const env = makeEnv();
    env.els.aasRuleName.value = 'Watch all';
    env.els.aasRuleTriggerType.value = 'container_state';
    env.states[0].checked = true;
    await env.ctx.saveAASRule();
    assert.deepStrictEqual(env.alerts, []);
    assert.deepStrictEqual(env.sent[0].body.trigger.containers, []);
  },

  async 'editing a container-state rule keeps it one'() {
    const env = makeEnv();
    const rule = { id: 'r1', name: 'Watch web', priority: 10, enabled: true,
      trigger: { type: 'container_state', states: ['unhealthy'], containers: ['db'],
        restart_threshold: 3, restart_window_minutes: 10, channel_ids: [], keywords: [],
        required_keywords: [], ignore_keywords: [], match_mode: 'any', regex_pattern: null,
        source_filter: { allowed_user_ids: [], allowed_usernames: [], is_webhook: null } },
      action: { type: 'RESTART', containers: [], delay_seconds: 0, notification_channel_id: null },
      safety: { cooldown_minutes: 30, cooldown_scope: 'container', only_if_running: true } };
    env.ctx.populateRuleForm(rule);
    await env.ctx.saveAASRule();
    assert.deepStrictEqual(env.alerts, []);
    const trigger = env.sent[0].body.trigger;
    assert.strictEqual(trigger.type, 'container_state');
    assert.deepStrictEqual(trigger.states, ['unhealthy']);
    assert.deepStrictEqual(trigger.containers, ['db']);
  },

  async 'a message rule is sent as before'() {
    const env = makeEnv();
    env.els.aasRuleName.value = 'Update restart';
    env.els.aasRuleChannelIds.value = '123';
    env.els.aasRuleKeywords.value = 'update';
    env.containers[0].checked = true;
    await env.ctx.saveAASRule();
    const body = env.sent[0].body;
    assert.strictEqual(body.trigger.type, undefined);
    assert.deepStrictEqual(body.trigger.channel_ids, ['123']);
    assert.deepStrictEqual(body.action.containers, ['web']);
  },
};

(async () => {
  let failed = 0;
  for (const [name, fn] of Object.entries(tests)) {
    try { await fn(); console.log('ok     ' + name); }
    catch (e) { failed += 1; console.log('FAILED ' + name + '\n       ' + e.message.split('\n').join('\n       ')); }
  }
  process.exit(failed ? 1 : 0);
})();
