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

function page(activeIndex) {
  // Sections stacked 1000 px apart, each 800 px tall; scrolled into one of them.
  const sections = {};
  ids.forEach((id, i) => { sections[id] = { top: i * 1000, height: 800 }; });
  const win = { scrollY: activeIndex * 1000 + 100, innerHeight: 900, listeners: {} };
  const dots = ['top', ...ids].map(id => ({
    href: '#' + id, classes: new Set(),
    getAttribute(name) { return name === 'href' ? this.href : null; },
    addEventListener() {},
    classList: null,
  }));
  dots.forEach(d => { d.classList = { add: c => d.classes.add(c), remove: c => d.classes.delete(c) }; });
  const nav = { querySelectorAll: () => dots };
  const document = {
    getElementById: id => (id === 'floatingNav' ? nav : sections[id] ? {
      getBoundingClientRect: () => ({ top: sections[id].top - win.scrollY, height: sections[id].height }),
    } : null),
    querySelector: () => null,
    documentElement: { scrollHeight: ids.length * 1000 },
  };
  const ctx = { document, window: Object.assign(win, {
    addEventListener(type, fn) { win.listeners[type] = fn; }, requestAnimationFrame: fn => fn(),
    scrollTo() {} }), console };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(root, 'app', 'static', 'js', 'floating_nav.js'), 'utf8'), ctx);
  return dots.filter(d => d.classes.has('active')).map(d => d.href.slice(1));
}

const cases = {
  'the bar has the channel translation dot'() {
    assert.ok(ids.includes('channel-translation-settings'), ids.join(', '));
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
