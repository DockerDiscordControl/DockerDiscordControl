// "Only when nobody plays" and the warning before a restart or stop (v3.1.0).
//
// The task form, the task edit dialog and the rule editor carry the same three
// fields in a block. Each caller names its own fields - task_form.js, tasks.js
// and auto_actions.js hold a table like
//     { PlayerGate: 'taskPlayerGate', WaitEmpty: 'taskWaitEmpty',
//       MaxWait: 'taskMaxWait', WarnMinutes: 'taskWarnMinutes' }
// so the script that sends a field is the one that names it. The server checks
// the values again (services/scheduling/player_gate.py normalize_options);
// these functions only read, fill and show them.

const PLAYER_GATE_ACTIONS = ['restart', 'stop'];

function playerGateField(fields, name) {
    const id = (fields || {})[name];
    return id ? document.getElementById(id) : null;
}

// The block is offered for restart and stop only - a start disturbs nobody.
function showPlayerOptions(fields, action) {
    const block = playerGateField(fields, 'PlayerGate');
    if (block) block.hidden = !PLAYER_GATE_ACTIONS.includes(action);
}

// The options for schedule_details.options; {} when nothing is switched on or
// the action does not take them.
function readPlayerOptions(fields, action) {
    if (!PLAYER_GATE_ACTIONS.includes(action)) return {};
    const wait = !!playerGateField(fields, 'WaitEmpty')?.checked;
    const warn = parseInt(playerGateField(fields, 'WarnMinutes')?.value || '0', 10) || 0;
    const options = {};
    if (wait) {
        options.wait_for_empty = true;
        options.max_wait_minutes = parseInt(playerGateField(fields, 'MaxWait')?.value || '120', 10) || 120;
    }
    if (warn > 0) options.warn_minutes = warn;
    return options;
}

function fillPlayerOptions(fields, options) {
    const o = options || {};
    const wait = playerGateField(fields, 'WaitEmpty');
    const maxWait = playerGateField(fields, 'MaxWait');
    const warn = playerGateField(fields, 'WarnMinutes');
    if (wait) wait.checked = !!o.wait_for_empty;
    if (maxWait) maxWait.value = o.max_wait_minutes || 120;
    if (warn) warn.value = o.warn_minutes || 0;
}
// One line for the task list: "only when empty (at most 120 min) · warning 10 min".
function describePlayerOptions(options, texts) {
    const o = options || {};
    const parts = [];
    if (o.wait_for_empty) parts.push(texts.whenEmpty.replace('{minutes}', o.max_wait_minutes || 120));
    if (o.warn_minutes) parts.push(texts.warning.replace('{minutes}', o.warn_minutes));
    return parts.join(' · ');
}

// Auto-action types in the words of the options: RESTART and RECREATE restart, STOP stops.
function playerGateActionOf(type) {
    return ({ RESTART: 'restart', RECREATE: 'restart', STOP: 'stop' })[String(type || '').toUpperCase()] || '';
}

if (typeof window !== 'undefined') {
    Object.assign(window, { showPlayerOptions, readPlayerOptions, fillPlayerOptions, describePlayerOptions,
                            playerGateActionOf });
}
