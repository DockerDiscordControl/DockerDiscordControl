# -*- coding: utf-8 -*-
"""A control that saves itself does not make the form look unsaved.

THE OPERATOR, 2026-09-24, after the debug switch was given its own save: "the
message still comes up." The box was German by then, which was the other half
of that report - but it still appeared.

I HAD FIXED THE HANDLER AND MISSED THE FORM. The switch's own listener no
longer raises the warning, and my case checked exactly that listener. But the
log view had moved INSIDE <form id="config-form"> that same morning, so that
the switch would be posted at all - and the form has a listener of its own
which reports everything inside it.

THAT LISTENER ALREADY HAD EXCEPTIONS, as a hard-coded list of three ids:

    if (e.target.id === 'taskFilterStatus' || e.target.closest('#taskListBody')
        || e.target.closest('.task-filters')) { return; }

A list, not a rule. So the fourth control that did not belong to the save had
to be remembered by somebody, and was not. The rule underneath all four is that
THE FORM'S SAVE IS ONE ACT - a token, a channel list and a language are changed
together and written together. A control that stores itself the moment it is
touched, and a filter that changes only what is shown, are not part of it.

So a control declares it in the markup, data-saves-itself="true", and
app/static/js/form_scope.js answers the question in one place for both
listeners.

WHAT THIS TEACHES ABOUT MY OWN TEST: it read the switch's handler and stopped
there. A page has more than one listener on the same event, and checking the
one I had just written is checking my own work rather than the behaviour. The
case below looks for EVERY place that raises the warning.

HOW THIS TEST CAN FAIL: a second listener raising the warning without asking,
or the exceptions going back to being a list of ids.

COUNTER-CHECK (2026-09-24): red before - the form's two listeners carried the
id list and the switch was not marked.
"""

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
PANEL_JS = PROJECT / "app" / "static" / "js" / "panel.js"
LOG_SECTION = PROJECT / "app" / "templates" / "_log_section.html"


def test_the_switch_declares_that_it_saves_itself():
    markup = LOG_SECTION.read_text(encoding="utf-8")
    tag = next(t for t in re.findall(r"<input\b[^>]*>", markup) if "debugLevelToggle" in t)

    assert 'data-saves-itself="true"' in tag, tag


def test_no_listener_raises_the_warning_without_asking():
    """THE MISS: I checked the listener I had written, and the form had
    another one. Every call is looked at now, not the one I remembered."""
    source = PANEL_JS.read_text(encoding="utf-8")
    # The calls that come from a listener on the form itself.
    blocks = re.findall(r"configForm\.addEventListener\((.*?)\n            \}\);",
                        source, re.S)

    assert len(blocks) >= 2, f"only {len(blocks)} form listeners found - pattern blind?"
    for block in blocks:
        if "showUnsavedChangesAlert" not in block:
            continue

        assert "belongsToTheFormSave" in block, (
            "a form listener raises the unsaved warning without asking whether "
            "the control belongs to the save:\n" + block[:300])


def test_the_exceptions_are_a_rule_and_not_a_list():
    """The three ids moved into one place, where the fourth case could be
    answered by a rule rather than by somebody remembering."""
    source = PANEL_JS.read_text(encoding="utf-8")

    assert "taskFilterStatus" not in source, (
        "the id list is back in panel.js - the next self-saving control will "
        "raise the warning again")
    assert (PROJECT / "app" / "static" / "js" / "form_scope.js").is_file()


def test_the_rule_is_loaded_before_the_panel_uses_it():
    scripts = (PROJECT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")

    assert "js/form_scope.js" in scripts
    assert scripts.index("js/form_scope.js") < scripts.index("js/panel.js")


def test_the_node_cases_exist():
    """The rule itself is exercised in node; the runtime image has no
    JavaScript engine."""
    cases = PROJECT / "tests" / "js" / "form_scope.test.js"

    assert cases.is_file()
    assert "belongsToTheFormSave" in cases.read_text(encoding="utf-8")


@pytest.mark.parametrize("marker", ['data-saves-itself="true"'])
def test_only_controls_that_really_save_themselves_are_marked(marker):
    """The marker switches the warning off for whatever carries it, so it is
    not something to sprinkle. Every element that has it must be one this
    suite can point at a save for."""
    marked = set()
    for path in sorted((PROJECT / "app" / "templates").rglob("*.html")):
        markup = path.read_text(encoding="utf-8")
        for tag in re.findall(r"<(?:input|select|textarea)\b[^>]*>", markup):
            if marker in tag:
                found = re.search(r'id="([^"]+)"', tag)
                if found:
                    marked.add(found.group(1))

    assert marked == {"debugLevelToggle"}, (
        f"these claim to save themselves: {sorted(marked)} - each needs a route "
        "that stores it, and a case that says so")
