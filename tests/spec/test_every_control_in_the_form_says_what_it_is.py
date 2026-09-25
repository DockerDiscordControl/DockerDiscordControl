# -*- coding: utf-8 -*-
"""A control inside the settings form is saved with it, or says why not.

THE OPERATOR, 2026-09-25, on picking a different log to read: "the save /
discard banner appears." Choosing which log to look at changes nothing, and
he asked in the same breath whether the banner is reliable enough to replace
the big "Save configuration" button.

IT WAS NOT. Measured: ``#config-form`` holds 87 controls, 66 of them carry a
``name`` and are written when the form is saved. The other 21 are not part of
that save at all - they belong to their own buttons, or they only change what
is shown - and every one of them raised the warning:

    11  the channel translation settings, which have saveCTSettings()
     4  the container query dialog, which has its own save
     2  the "add admin" fields, which have their own button
     1  the container search box, which filters a table
     2  the log type and its auto-refresh, which display things
     1  the task status filter - the ONLY one already excepted

THE SAME MISTAKE, ONE LAYER UP. On 2026-09-24 a hard-coded list of three ids
was replaced by a marker in the markup, because "a list, not a rule" had let
the debug switch slip through. The comment written that day already names the
second category - "a filter that changes only what is shown" - but no marker
was made for it, so it stayed a list of one. This file is the rule that stops
the third round: EVERY unnamed control in the form has to declare itself, and
a new one cannot be forgotten because nobody remembered to add it anywhere.

THE TWO DECLARATIONS, and they mean different things:

    data-saves-itself="true"       persisted by something other than this
                                   form's Save - its own button, its own
                                   route, or the moment it is touched
    data-changes-the-view="true"   persists nothing at all: a filter, a
                                   selector, a test box

WHY ``name`` IS THE DIVIDING LINE. The save walks the form's controls and
writes ``formData.set(element.name, …)``, so a control without a name cannot
reach the configuration - with one exception worth knowing: checkboxes and
radios are set without checking for a name first, which is how an unnamed box
writes an empty key. The named controls are not asked to declare anything;
they are the save.

WHICH TEMPLATES COUNT is read out of config.html - the includes that sit
between <form id="config-form"> and its </form> - rather than listed here,
because a list of templates would go stale exactly like the list of ids did.

HOW THIS TEST CAN FAIL: a control added inside the form with no name and no
declaration, or a declaration on a control that is part of the save after all.

COUNTER-CHECK (2026-09-25): red before - twenty undeclared controls.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
TEMPLATES = PROJECT / "app" / "templates"
CONFIG = TEMPLATES / "config.html"

SAVES_ITSELF = 'data-saves-itself="true"'
CHANGES_THE_VIEW = 'data-changes-the-view="true"'

# Built at runtime and carrying no markup of their own, so they are named in
# app/static/js/form_scope.js instead. Repeated here only to keep them out of
# the count - the rule for them lives there.
ALREADY_A_RULE = {"taskFilterStatus"}

A_CONTROL = re.compile(r"<(?:input|select|textarea)\b[^>]*>", re.S)


def _templates_inside_the_form():
    """The includes between the form's opening tag and its close."""
    markup = CONFIG.read_text(encoding="utf-8")
    start = markup.index('<form method="POST" id="config-form">')
    end = markup.index("</form>", start)
    return [TEMPLATES / name
            for name in re.findall(r"{%\s*include\s*'([^']+)'", markup[start:end])]


def _controls_without_a_name():
    """(template, id, tag) for every control the save cannot reach."""
    for path in _templates_inside_the_form():
        if not path.exists():
            continue
        for tag in A_CONTROL.findall(path.read_text(encoding="utf-8")):
            if 'type="hidden"' in tag or "name=" in tag:
                continue
            found = re.search(r'id="([^"]+)"', tag)
            yield path.name, (found.group(1) if found else tag[:60]), tag


def test_every_unnamed_control_declares_what_it_is():
    """THE FINDING: twenty controls that the save never writes, all of them
    telling the operator he has unsaved changes."""
    undeclared = sorted(
        f"{template}:{identifier}"
        for template, identifier, tag in _controls_without_a_name()
        if identifier not in ALREADY_A_RULE
        and SAVES_ITSELF not in tag and CHANGES_THE_VIEW not in tag)

    assert undeclared == [], (
        "these sit inside the settings form, are never written by its save, "
        f"and still raise the unsaved-changes banner: {undeclared}")


def test_the_scan_looks_at_the_right_form():
    """The counter-check eleven sabotages have walked past: a scan over an
    empty set passes the case above while proving nothing."""
    templates = _templates_inside_the_form()

    assert len(templates) >= 8, [p.name for p in templates]
    assert any(p.name == "_log_section.html" for p in templates), [p.name for p in templates]

    controls = list(_controls_without_a_name())

    assert len(controls) >= 15, len(controls)


def test_a_named_control_needs_no_declaration():
    """The opposite mistake. The 66 named controls ARE the save, and asking
    them to declare anything would make the rule meaningless."""
    named = 0
    for path in _templates_inside_the_form():
        if not path.exists():
            continue
        for tag in A_CONTROL.findall(path.read_text(encoding="utf-8")):
            if "name=" in tag and 'type="hidden"' not in tag:
                named += 1
                assert CHANGES_THE_VIEW not in tag, (
                    f"a control the save writes claims to change only the view: {tag[:90]}")

    assert named >= 50, named


def test_nothing_claims_both():
    """Persisting elsewhere and persisting nothing are different answers, and
    a control that gives both is one nobody has actually classified."""
    both = [f"{template}:{identifier}"
            for template, identifier, tag in _controls_without_a_name()
            if SAVES_ITSELF in tag and CHANGES_THE_VIEW in tag]

    assert both == [], both


def test_the_rule_knows_the_second_declaration():
    """A marker nothing reads would leave the banner exactly as it was."""
    rule = (PROJECT / "app" / "static" / "js" / "form_scope.js").read_text(encoding="utf-8")

    assert "data-changes-the-view" in rule, (
        "the markers are in the templates but form_scope.js still asks for "
        "only one of them")
    assert "data-saves-itself" in rule
