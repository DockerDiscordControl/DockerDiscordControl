// Runs app/static/js/advanced_settings_modal.js in node: does the difficulty
// card save what it says it saves? Called from
// tests/spec/test_the_difficulty_card_saves_when_it_says_it_does.py.
//
// THE OPERATOR, 2026-09-26, pointing at the card: "you have to check this one
// too, whether it works at all."
//
// THE CARD PROMISES, in blue with a lightning bolt and in all forty languages:
// "Changes saved immediately". Underneath it are a slider and three preset
// buttons - and until this file was written, neither wrote anything.
//
//   setDifficulty(2.0)   set slider.value, redrew the label, and called
//                        enableManualOverride(), which returns at once when
//                        the switch is ALREADY on - the state in which the
//                        buttons are usable at all
//   onSliderChange()     the same, per pixel of the drag
//
// The only caller of saveMechDifficulty() was saveAdvancedSettings(), the
// modal's footer Save. So the operator could drag to 2.00x, read "Current:
// 2.00x", close the dialog with Cancel or the X, and keep the old value -
// while the panel had told him it was already saved.
//
// The promise is the part that is right: it exists in forty catalogues and it
// is what a control with no Save button of its own ought to do. The controls
// were brought up to it rather than the sentence down to them.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

// --- the smallest DOM this file needs ---------------------------------------
function harness({ overrideOn = true, sliderValue = '1.0' } = {}) {
  const posted = [];
  const slider = { id: 'mech_difficulty_multiplier', value: sliderValue, disabled: !overrideOn,
                   style: {} };
  const toggle = { id: 'mech_manual_difficulty_override_standalone', checked: overrideOn,
                   closest: () => ({ querySelector: () => ({ style: {} }) }) };
  const text = () => ({ textContent: '' });
  const byId = {
    mech_difficulty_multiplier: slider,
    mech_manual_difficulty_override_standalone: toggle,
    difficultyValue: text(),
    levelCostPreview: text(),
    levelCostDetails: text(),
  };

  const sandbox = {
    console: { log() {}, error() {}, warn() {} },
    setTimeout() {},
    document: {
      getElementById: (id) => byId[id] || null,
      querySelectorAll: () => [],
      addEventListener() {},
    },
    // Every call is recorded; the answer is the shape the real route gives.
    fetch: (url, options) => {
      posted.push({ url, options, body: options && options.body ? JSON.parse(options.body) : null });
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ success: true, message: 'ok' }),
      });
    },
    t: (key) => key,
    // The page's, from config-ui.js (the file under test no longer declares
    // its own console-only one - tests/js/notifications.test.js).
    showNotification() {},
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', 'app', 'static', 'js',
    'advanced_settings_modal.js'), 'utf8'), sandbox);

  return { sandbox, posted, slider, toggle,
           writes: () => posted.filter(p => p.url === '/api/mech/difficulty') };
}

// Promises resolve on the microtask queue; the calls under test are async.
const settle = () => new Promise(resolve => setImmediate(resolve));

const cases = {
  async 'a preset button writes its value'() {
    // THE FINDING. The switch is already on, which is the only state in
    // which the buttons can be pressed at all.
    const h = harness({ overrideOn: true });
    h.sandbox.setDifficulty(2.0);
    await settle();

    const writes = h.writes();
    assert.strictEqual(writes.length, 1, `expected one write, got ${writes.length}`);
    assert.strictEqual(writes[0].body.difficulty_multiplier, 2.0);
    assert.strictEqual(writes[0].body.manual_override, true);
  },

  async 'letting go of the slider writes where it was left'() {
    const h = harness({ overrideOn: true, sliderValue: '1.0' });
    h.slider.value = '1.7';
    h.sandbox.onSliderChange(true);
    await settle();

    const writes = h.writes();
    assert.strictEqual(writes.length, 1, `expected one write, got ${writes.length}`);
    assert.strictEqual(writes[0].body.difficulty_multiplier, 1.7);
  },

  async 'dragging it does not write once per pixel'() {
    // THE OPPOSITE MISTAKE. A range fires input for every step of the drag;
    // a save on each would be forty requests for one decision.
    const h = harness({ overrideOn: true });
    for (const value of ['1.1', '1.2', '1.3', '1.4']) {
      h.slider.value = value;
      h.sandbox.onSliderChange();
    }
    await settle();

    assert.strictEqual(h.writes().length, 0, 'the drag itself wrote to the server');
  },

  async 'the first touch turns the switch on and writes once'() {
    // With the override OFF the controls are disabled, but a keyboard or a
    // script can still reach them - and the old code did save in this one
    // case, by flipping the switch. It must not now write twice, once with
    // manual_override false and once true.
    const h = harness({ overrideOn: false });
    h.slider.value = '0.5';
    h.sandbox.onSliderChange(true);
    await settle();

    const writes = h.writes();
    assert.strictEqual(writes.length, 1, `expected one write, got ${writes.length}`);
    assert.strictEqual(writes[0].body.manual_override, true);
    assert.strictEqual(writes[0].body.difficulty_multiplier, 0.5);
    assert.strictEqual(h.toggle.checked, true, 'the switch did not follow');
  },

  async 'redrawing the label writes nothing'() {
    // The display function is called on load as well. A save there would
    // write the server's own answer back to it on every open.
    const h = harness({ overrideOn: true });
    h.sandbox.updateDifficultyDisplay();
    await settle();

    assert.strictEqual(h.writes().length, 0, 'merely showing the value wrote to the server');
  },

  async 'the recorder would have seen a write'() {
    // The counter-check the sabotages keep walking past: every case above
    // passes on a harness that cannot record anything.
    const h = harness({ overrideOn: true });
    h.sandbox.saveMechDifficulty(1.3);
    await settle();

    assert.strictEqual(h.writes().length, 1, 'the harness records no writes at all');
    assert.strictEqual(h.writes()[0].options.method, 'POST');
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
