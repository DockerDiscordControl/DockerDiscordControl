# -*- coding: utf-8 -*-
"""A button wired to a name is only alive if the page carries that name.

THE OPERATOR, 2026-09-26, after two controls in one evening turned out not to
do what they said: "maybe even extend it with tests, to cover the most common
errors."

THIS IS THAT CLASS, AND IT IS THE WEEK'S OWN. A control that looks alive and
is dead has been the finding four times over - an expand button nobody could
press, three cooldown sliders that steered nothing, a documentation button
opening a host that does not exist, a difficulty slider that saved nothing.
Thirty-eight of this panel's controls are wired by an attribute::

    <button onclick="setDifficulty(2.0)">

and an attribute is a string. Rename the function, move it to a script this
page does not load, mistype it, and the markup still renders a button that
looks exactly like a working one. Nothing fails, nothing is logged: the
browser writes one line to a console the operator never opens.

EVERY FIX SO FAR WAS APPLIED WHERE THE SYMPTOM WAS. This is the same rule
asked everywhere the pattern is.

WHAT IS CHECKED, AND HOW ITS SUBJECTS ARE FOUND. Not a list - a list would go
stale exactly like the wiring it guards. Each page that is not a partial is
followed through its own ``{% include %}`` and ``{% extends %}``, so the set
of markup a page really renders is read out of the markup; the scripts that
page loads are read from the same family; and every bare call in an inline
handler in it has to be a name one of those scripts defines, or one defined
in an inline script of the family.

WHAT IS NOT A SUBJECT: a method call. ``this.form.submit()`` and
``window.open(...)`` are the browser's own, not the panel's, and the scan
skips a name that follows a dot for that reason.

HOW THIS TEST CAN FAIL: a control wired to a name the page does not carry -
by a rename, by a typo, or by the defining script being loaded on a different
page.

COUNTER-CHECK (2026-09-26): green at birth, which is what a guard should be.
Proved able to fail by two sabotages, each asserted to have changed the file
it touched: a renamed handler in the markup, and the difficulty script
removed from the page that uses it.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"
SCRIPTS = PROJECT / "app" / "static" / "js"

# A call on something, not a call of something: `x.open(` is the browser's.
A_CALL = re.compile(r"(?<![\w.$])([A-Za-z_]\w*)\s*\(")
A_HANDLER = re.compile(r'\bon[a-z]+="([^"]*)"')
DEFINES = (
    re.compile(r"function\s+(\w+)\s*\("),
    re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function|\()"),
    re.compile(r"window\.(\w+)\s*="),
)
# Things the language itself answers for.
THE_LANGUAGES_OWN = {"if", "for", "while", "return", "typeof", "alert", "confirm",
                     "parseInt", "parseFloat", "Number", "String", "Boolean", "Array",
                     "Object", "Date", "Math", "JSON", "RegExp", "Promise", "Error"}


def _family(page, seen=None):
    """Every template a page really renders, read out of the markup."""
    seen = set() if seen is None else seen
    path = TEMPLATES / page
    if page in seen or not path.exists():
        return seen
    seen.add(page)
    markup = path.read_text(encoding="utf-8")
    for other in re.findall(r"{%-?\s*(?:include|extends)\s*'([^']+)'", markup):
        _family(other, seen)
    return seen


def _pages():
    """A page is a template nothing includes - the ones a route renders."""
    return sorted(p.name for p in TEMPLATES.glob("*.html") if not p.name.startswith("_"))


def _what_the_page_carries(family):
    """Every function name reachable from the page: its scripts, and the
    inline scripts of its own templates."""
    names, loaded = set(), set()
    for member in family:
        markup = (TEMPLATES / member).read_text(encoding="utf-8")
        loaded |= set(re.findall(r"filename='js/([\w.-]+)'", markup))
        loaded |= set(re.findall(r'src="/static/js/([\w.-]+)"', markup))
        for block in re.findall(r"<script\b[^>]*>(.*?)</script>", markup, re.S):
            for pattern in DEFINES:
                names |= set(pattern.findall(block))
    for script in loaded:
        path = SCRIPTS / script
        if path.exists():
            source = path.read_text(encoding="utf-8")
            for pattern in DEFINES:
                names |= set(pattern.findall(source))
    return names, loaded


def _wiring():
    """{page: [(template, handler name)]} for every inline handler."""
    found = {}
    for page in _pages():
        family = _family(page)
        for member in sorted(family):
            markup = (TEMPLATES / member).read_text(encoding="utf-8")
            for body in A_HANDLER.findall(markup):
                for name in A_CALL.findall(body):
                    if name not in THE_LANGUAGES_OWN:
                        found.setdefault(page, []).append((member, name))
    return found


def test_every_wired_control_reaches_a_name_the_page_carries():
    """THE RULE. A dead handler renders a button that looks exactly like a
    working one."""
    dead = []
    for page, wired in _wiring().items():
        carried, _loaded = _what_the_page_carries(_family(page))
        for member, name in wired:
            if name not in carried:
                dead.append(f"{page} -> {member}: {name}()")

    assert dead == [], (
        "controls are wired to names their page does not carry, so they "
        "render as working buttons and do nothing:\n  " + "\n  ".join(sorted(set(dead))))


def test_the_scan_found_the_panel_and_not_an_empty_room():
    """The counter-check the sabotages keep walking past: the rule above
    passes on zero handlers and zero pages."""
    wiring = _wiring()
    every = {name for wired in wiring.values() for _m, name in wired}

    assert len(_pages()) >= 4, _pages()
    assert len(every) >= 30, sorted(every)
    # Two that are known to be there, from opposite corners of the panel.
    assert "setDifficulty" in every, sorted(every)
    assert "saveAdvancedSettings" in every, sorted(every)


def test_the_families_are_really_followed():
    """The rule is only as wide as the include graph it walks. config.html
    renders its controls almost entirely through partials, so a family that
    stopped at the page itself would check nearly nothing."""
    family = _family("config.html")

    assert len(family) > 15, sorted(family)
    assert "_advanced_settings_modal.html" in family, sorted(family)
    assert "_base.html" in family, "the shell is not followed, so no script is found"


def test_the_pages_really_load_scripts():
    """And the names have to come from somewhere. A page whose script list
    came out empty would make every handler on it look dead - or, with the
    inline fallback, make the rule toothless."""
    carried, loaded = _what_the_page_carries(_family("config.html"))

    assert len(loaded) >= 5, sorted(loaded)
    assert "advanced_settings_modal.js" in loaded, sorted(loaded)
    assert len(carried) >= 100, len(carried)


def test_a_method_call_is_not_treated_as_a_handler():
    """this.form.submit() and window.open() are the browser's own. A scan
    that claimed them would go red on markup that is perfectly alive - and
    the first version of this file did exactly that."""
    assert A_CALL.findall("this.form.submit()") == []
    assert A_CALL.findall("window.open('x', '_blank')") == []
    assert A_CALL.findall("setDifficulty(2.0)") == ["setDifficulty"]
    assert A_CALL.findall("saveCTPair(); filterCTPairs()") == ["saveCTPair", "filterCTPairs"]
