// Runs app/static/js/spam_protection_modal.js in node: the save writes what
// the dialog shows. Called from
// tests/spec/test_the_spam_dialog_saves_what_it_shows.py.
//
// THE FINDING (2026-09-26). The dialog READS its settings with a loop over
// whatever the server sent, and WROTE them back from a list of twenty-four
// names typed into the file. Five of those names have no field in the markup:
//
//     button_admin_overview_admin          button_admin_overview_stop_all
//     button_admin_overview_restart_all    button_admin_overview_restart_stack
//     button_admin_overview_donate
//
// so the save reached for them with `?.value || 5` and wrote a number out of
// the source - a cooldown nobody could see, nobody could change, and every
// Save pinned into the configuration. The comment above those five lines had
// warned about exactly this shape since it was written, pointing the other way:
// "a slider missing HERE is rendered and then dropped on save".
//
// A LIST GOES STALE LIKE THE THING IT GUARDS. The save now reads the same
// fields the load fills - every `button_*` and `cooldown_*` in the dialog -
// so a slider that exists is saved, one that does not exist is not invented,
// and neither half can drift from the other again.
//
// WHAT THE SERVER DOES WITH A MISSING ONE: spam_protection_service merges the
// saved settings over its own defaults, so a cooldown the dialog no longer
// sends keeps the default it always had. Nothing is lost by not writing it.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

// --- the smallest DOM this file needs ---------------------------------------
const SWITCHES = ['spamProtectionEnabled', 'cooldownMessage', 'logViolations'];
const NUMBERS = ['maxCommandsPerMinute', 'maxButtonsPerMinute'];
// What the markup really carries, minus the five that are not there.
const COMMANDS = ['control', 'serverstatus', 'info', 'help', 'ping', 'donate',
                  'language', 'forceupdate'];
const BUTTONS = ['start', 'stop', 'restart', 'info', 'logs', 'live_refresh',
                 'mech_donate', 'mech_history', 'mech_details', 'mech_display',
                 'mech_story', 'mech_music', 'admin', 'help', 'tasks',
                 'task_delete', 'edit_info', 'protected_info',
                 'protected_info_edit'];

function harness({ extraButtons = [] } = {}) {
  const posted = [];
  const byId = {};
  const fields = [];
  const field = (id, value) => {
    const el = { id, value: String(value), checked: true };
    byId[id] = el;
    fields.push(el);
    return el;
  };
  SWITCHES.forEach(id => field(id, ''));
  // The module attaches listeners to the dialog and the Save button on import.
  // The module attaches listeners to the dialog and the Save button on
  // import. The dialog's is kept, because opening the dialog is the only way
  // to reach the load - and the load is what sets the module's own
  // spamSettingsLoaded, a top-level `let` that nothing outside the script can
  // assign. A first version set it on the sandbox and every case came back
  // "nothing was saved at all".
  const opened = [];
  const inTheDialog = (selector) => {
    const prefix = /\[id\^="([\w-]+)"\]/.exec(selector);
    return prefix ? fields.filter(el => el.id.startsWith(prefix[1])) : [];
  };
  byId['spamProtectionModal'] = {
    id: 'spamProtectionModal',
    addEventListener(name, run) { opened.push(run); },
    querySelectorAll: inTheDialog,
  };
  byId['saveSpamProtection'] = { id: 'saveSpamProtection', addEventListener() {} };
  NUMBERS.forEach((id, i) => field(id, 10 + i));
  COMMANDS.forEach((name, i) => field('cooldown_' + name, 100 + i));
  BUTTONS.concat(extraButtons).forEach((name, i) => field('button_' + name, 200 + i));

  const sandbox = {
    console: { log() {}, error() {}, warn() {} },
    alert() {},
    setTimeout() {},
    document: {
      getElementById: (id) => byId[id] || null,
      // The page, deliberately empty: the save must ask the DIALOG, and a
      // case that let it sweep the whole document would not notice.
      querySelectorAll: () => [],
      addEventListener(name, run) { sandbox._ready = run; },
    },
    fetch: (url, options) => {
      if (!options || !options.method || options.method === 'GET') {
        // What the dialog reads when it opens. The five that are missing from
        // the markup are sent, as the server really sends them - the load
        // loop skips a field that is not there, which is how they came to be
        // written back from a literal instead.
        const button_cooldowns = {};
        BUTTONS.forEach((name, i) => { button_cooldowns[name] = 200 + i; });
        ['admin_overview_admin', 'admin_overview_restart_all', 'admin_overview_stop_all',
         'admin_overview_restart_stack', 'admin_overview_donate']
          .forEach(name => { button_cooldowns[name] = 99; });
        const command_cooldowns = {};
        COMMANDS.forEach((name, i) => { command_cooldowns[name] = 100 + i; });
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve({
            global_settings: {
              enabled: true, cooldown_message: true, log_violations: true,
              max_commands_per_minute: 10, max_buttons_per_minute: 11,
            },
            command_cooldowns, button_cooldowns,
          }),
        });
      }
      posted.push({ url, body: options.body ? JSON.parse(options.body) : null });
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ success: true }),
      });
    },
    t: (key) => key,
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
    'spam_protection_modal.js'), 'utf8'), sandbox);
  // Open the dialog, which is what loads the settings and lets a save through.
  const loaded = Promise.all(opened.map(run => run()));
  return { sandbox, posted, byId, loaded,
           saved: () => (posted[0] && posted[0].body) || null };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

const cases = {
  async 'it saves no cooldown the dialog does not show'() {
    // THE FINDING: five names with no field, written from a literal.
    const h = harness();
    await h.loaded; await settle();
    h.sandbox.saveSpamProtection();
    await settle();

    const saved = h.saved();
    assert.ok(saved, 'nothing was saved at all');
    for (const ghost of ['admin_overview_admin', 'admin_overview_restart_all',
                         'admin_overview_stop_all', 'admin_overview_restart_stack',
                         'admin_overview_donate']) {
      assert.ok(!(ghost in saved.button_cooldowns),
        `${ghost} was saved although no field shows it: ${saved.button_cooldowns[ghost]}`);
    }
  },

  async 'it saves every cooldown the dialog does show'() {
    const h = harness();
    await h.loaded; await settle();
    h.sandbox.saveSpamProtection();
    await settle();

    const saved = h.saved();
    for (const name of BUTTONS) {
      assert.ok(name in saved.button_cooldowns, `${name} was not saved`);
    }
    for (const name of COMMANDS) {
      assert.ok(name in saved.command_cooldowns, `${name} was not saved`);
    }
  },

  async 'a slider added later is saved without being listed'() {
    // The half that makes the list unable to go stale again: the markup gains
    // a field and the save picks it up, with no second place to edit.
    const h = harness({ extraButtons: ['brand_new_control'] });
    await h.loaded; await settle();
    h.sandbox.saveSpamProtection();
    await settle();

    assert.ok('brand_new_control' in h.saved().button_cooldowns,
      'a field in the dialog was not saved');
  },

  async 'it saves the numbers that are in the fields'() {
    // Counter-check: a save that wrote the right KEYS and the wrong VALUES
    // would pass everything above.
    const h = harness();
    await h.loaded; await settle();
    // AFTER the load, which fills every field from the server.
    h.byId['button_start'].value = '42';
    h.byId['cooldown_ping'].value = '7';
    h.sandbox.saveSpamProtection();
    await settle();

    assert.strictEqual(h.saved().button_cooldowns.start, 42);
    assert.strictEqual(h.saved().command_cooldowns.ping, 7);
  },

  async 'it refuses to save what it has not loaded'() {
    // The rule that was already here and must stay: saving a form still
    // showing its own start values would write them over the server's.
    const h = harness();
    h.sandbox.spamSettingsLoaded = false;
    h.sandbox.saveSpamProtection();
    await settle();

    assert.strictEqual(h.posted.length, 0, 'it saved an unloaded form');
  },

  async 'the harness would have seen a write'() {
    const h = harness();
    await h.loaded; await settle();
    h.sandbox.saveSpamProtection();
    await settle();

    assert.strictEqual(h.posted.length, 1, 'the harness records no writes at all');
    assert.ok(h.posted[0].url.includes('spam'), h.posted[0].url);
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
      console.log('FAIL - ' + name + ': ' + (e.stack || e.message));
    }
  }
  process.exit(failed === 0 ? 0 : 1);
})();
