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
    'aasMessageTriggerFields', 'aasContainerTriggerFields', 'aasRuleCpuThreshold',
    'aasRuleMemoryThreshold', 'aasRuleResourceMinutes',
    // Added 2026-09-24 with the memory watchdog's second threshold: the form
    // reads it on every save and on every edit, so leaving it out of the
    // stand-in made every case here fail on a null element.
    'aasRuleMemoryThresholdMb'];
  for (const id of ids) {
    els[id] = { id, value: '', checked: false, focus() {}, style: {},
      classList: { add() {}, remove() {}, toggle() {} } };
  }
  els.aasRuleMatchMode.value = 'any';
  els.aasRuleActionType.value = 'NOTIFY';
  els.aasRuleCooldownScope.value = 'container';
  els.aasRuleTriggerType.value = 'message';
  const containers = ['web', 'db'].map(value => ({ value, checked: false }));
  // A rule may target a GROUP as well as a container since 2026-09-23, and the
  // save reads one combined selector for both (auto_actions.js). The stand-in
  // answered only the container half and returned nothing for the combined
  // string, so every save here sent an empty target list.
  const groups = ['group:Gameserver'].map(value => ({ value, checked: false }));

  // Opening a rule for editing REDRAWS the target checkboxes: the editor writes
  // them into this wrapper as HTML, and the browser then has the boxes the save
  // reads back. The stand-in does the same thing by reading what the editor
  // just wrote - so a rule that holds a target it cannot see keeps it, which is
  // the whole point of rule_targets.js. Without this the wrapper swallowed the
  // HTML and every edited rule saved an empty target list.
  const targetWrapper = {
    id: 'aasRuleTargetContainersWrapper', style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    set innerHTML(html) {
      containers.length = 0;
      groups.length = 0;
      const box = /<input[^>]*class="[^"]*aas-(container|group)-checkbox"[^>]*>/g;
      for (const [tag, kind] of [...html.matchAll(box)].map(m => [m[0], m[1]])) {
        const value = /value="([^"]*)"/.exec(tag);
        (kind === 'group' ? groups : containers).push(
          { value: value ? value[1] : '', checked: /\bchecked\b/.test(tag) });
      }
    },
    get innerHTML() { return ''; },
  };
  const states = ['stopped', 'unhealthy', 'restart_loop', 'high_cpu', 'high_memory']
    .map(value => ({ value, checked: false }));
  const feedback = [{ value: '', checked: true }, { value: '555', checked: false }];
  els.aasRuleTargetContainersWrapper = targetWrapper;
  const document = {
    getElementById: id => els[id] || null,
    // escapeHtml() escapes by writing text into a node and reading the markup
    // back. Only the four characters that matter here, so a group called
    // Plex "4K" is still escaped the way the browser would escape it.
    createElement: () => ({
      textContent: '',
      get innerHTML() {
        return String(this.textContent)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      },
    }),
    addEventListener() {},
    querySelectorAll(sel) {
      if (sel === '.aas-container-checkbox:checked') return containers.filter(b => b.checked);
      if (sel === '.aas-container-checkbox') return containers;
      if (sel === '.aas-group-checkbox:checked') return groups.filter(b => b.checked);
      if (sel === '.aas-group-checkbox') return groups;
      if (sel === '.aas-container-checkbox:checked, .aas-group-checkbox:checked') {
        return containers.concat(groups).filter(b => b.checked);
      }
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
  // BOTH files, in the order _scripts.html loads them. auto_actions.js calls
  // saveWidensToEveryContainer(), which lives in rule_targets.js - loading only
  // auto_actions.js left every case here failing with "not defined" from
  // 2026-09-23 (commit 2652aafd) until 2026-09-24, because this file only ever
  // runs by hand and nobody ran it. The sandbox mirrors the page.
  const js = (name) => fs.readFileSync(
    path.join(__dirname, '..', '..', 'app', 'static', 'js', name), 'utf8');
  vm.runInContext(js('rule_targets.js'), ctx);
  vm.runInContext(js('auto_actions.js'), ctx);
  ctx.loadAASRules = () => {};
  return { ctx, els, containers, groups, states, sent, alerts };
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

  async 'resource thresholds are sent and kept on edit'() {
    const env = makeEnv();
    env.els.aasRuleName.value = 'Hot';
    env.els.aasRuleTriggerType.value = 'container_state';
    env.states[3].checked = true;  // high_cpu
    env.els.aasRuleCpuThreshold.value = '85';
    env.els.aasRuleMemoryThreshold.value = '95';
    env.els.aasRuleResourceMinutes.value = '7';
    await env.ctx.saveAASRule();
    const trigger = env.sent[0].body.trigger;
    assert.deepStrictEqual(trigger.states, ['high_cpu']);
    assert.strictEqual(trigger.cpu_threshold_percent, 85);
    assert.strictEqual(trigger.memory_threshold_percent, 95);
    assert.strictEqual(trigger.resource_minutes, 7);

    const edit = makeEnv();
    edit.ctx.populateRuleForm({ id: 'r', name: 'Hot', priority: 10, enabled: true,
      trigger: { ...trigger, restart_threshold: 3, restart_window_minutes: 10 },
      action: { type: 'NOTIFY', containers: [], delay_seconds: 0, notification_channel_id: null },
      safety: { cooldown_minutes: 30, cooldown_scope: 'container', only_if_running: true } });
    await edit.ctx.saveAASRule();
    const again = edit.sent[0].body.trigger;
    assert.deepStrictEqual([again.cpu_threshold_percent, again.memory_threshold_percent, again.resource_minutes],
      [85, 95, 7]);
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
