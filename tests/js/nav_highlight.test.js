// Runs app/static/js/floating_nav.js in node against the dots of the real
// base.html: every dot lights up while its section is in view. Called from
// tests/spec/test_every_nav_dot_lights_up.py.
//
// THE OPERATOR (2026-09-27): the new channel-translation dot "is not
// highlighted like the others when I have the section in focus - please check
// all nav bar highlighters". floating_nav.js kept its own list of section ids,
// and a dot added to the bar was missing from it.
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');

const root = path.join(__dirname, '..', '..');
const base = fs.readFileSync(path.join(root, 'app', 'templates', 'base.html'), 'utf8');
const ids = [...base.matchAll(/<a href="#([^"]+)" class="nav-dot"/g)].map(m => m[1]).filter(id => id !== 'top');

// A page of sections at the given {top, height}, scrolled to scrollY, in a
// window innerHeight tall; the document ends where the last section ends.
function render(layout, scrollY, innerHeight = 900) {
  const win = { scrollY, innerHeight, listeners: {} };
  const dots = ['top', ...ids].map(id => ({
    href: '#' + id, classes: new Set(),
    getAttribute(name) { return name === 'href' ? this.href : null; },
    addEventListener() {},
    classList: null,
  }));
  dots.forEach(d => { d.classList = { add: c => d.classes.add(c), remove: c => d.classes.delete(c) }; });
  const nav = { querySelectorAll: () => dots };
  const end = Math.max(...Object.values(layout).map(b => b.top + b.height));
  const document = {
    getElementById: id => (id === 'floatingNav' ? nav : layout[id] ? {
      getBoundingClientRect: () => ({ top: layout[id].top - win.scrollY, height: layout[id].height }),
    } : null),
    querySelector: () => null,
    documentElement: { scrollHeight: end, clientHeight: innerHeight },
    body: { scrollHeight: end },
  };
  const ctx = { document, window: Object.assign(win, {
    addEventListener(type, fn) { win.listeners[type] = fn; }, requestAnimationFrame: fn => fn(),
    scrollTo() {} }), console };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(root, 'app', 'static', 'js', 'floating_nav.js'), 'utf8'), ctx);
  return dots.filter(d => d.classes.has('active')).map(d => d.href.slice(1));
}

// Sections stacked 1000 px apart, each 800 px tall (200 px gaps: the <hr>
// and margins between cards).
function stacked() {
  const layout = {};
  ids.forEach((id, i) => { layout[id] = { top: i * 1000, height: 800 }; });
  return layout;
}

function page(activeIndex) {
  return render(stacked(), activeIndex * 1000 + 100);
}

const cases = {
  'the bar has the channel translation dot'() {
    assert.ok(ids.includes('channel-translation-settings'), ids.join(', '));
  },
  // THE OPERATOR (2026-09-27, again): the channel translation still did not
  // light up, nor the Auto-Action System - both the LAST section of their tab.
  // The page cannot scroll far enough for the 150 px line to reach them, so
  // the section above stayed lit (the task list, in his screenshot).
  'a short last section lights up once the page is at its end'() {
    const layout = {};
    layout['task-list'] = { top: 0, height: 1500 };
    layout['aas-section'] = { top: 1600, height: 300 };
    const bottom = 1900 - 900;  // scrolled as far as the page goes
    assert.deepStrictEqual(render(layout, bottom), ['aas-section']);
  },
  // In the 200 px between two cards the line is in no section at all, and no
  // dot was lit (his first screenshot). The section above keeps its light.
  'the gap between two sections keeps the section above lit'() {
    const lit = render(stacked(), 1 * 1000 + 850 - 150);  // line at 1850: the gap after the second
    assert.deepStrictEqual(lit, [ids[1]]);
  },
  'every dot lights up over its own section'() {
    const dark = ids.filter((id, i) => JSON.stringify(page(i)) !== JSON.stringify([id]));
    assert.deepStrictEqual(dark, [], `these dots never light up: ${dark.join(', ')}`);
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(cases)) {
  try { fn(); console.log('ok     ' + name); }
  catch (e) { failed += 1; console.log('FAILED ' + name + '\n       ' + e.message); }
}
process.exit(failed ? 1 : 0);
