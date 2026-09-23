# -*- coding: utf-8 -*-
"""The container table can act on a whole group at once.

THE GAP, measured on 2026-09-23: the operator's own container groups reach the
scheduled tasks (a task can target a group) and the auto-action rule targets (a
rule can watch a group). The container section of the panel - the table where
every container's Active flag and its four allowed actions are set - knows
nothing about them. With 26 containers that is 26 rows and up to 130 tick
boxes, one at a time, for a change that belongs to a group.

The operator asked for groups to work THROUGHOUT the admin panel, and said
explicitly: no Compose stacks, only his own groupings. So this is the groups
from services/config/group_service.py, not the com.docker.compose.project
label the sort button uses (measured the same day: 0 of 26 containers carry
that label).

WHAT IT DOES: pick a group, tick the permissions wanted, apply. Every row of
that group on the page is switched Active and given exactly those permissions.
"Remove" switches the group's rows off again. Nothing is saved by this - it
fills in the form the operator then saves, which is why it needs no endpoint
and cannot half-apply.

WHY THE MISSING CONTAINERS MATTER: a group resolves against the containers DDC
steers; the table lists what the host has now. A group naming a container that
is no longer there must SAY so - otherwise "apply to group" quietly acts on
five of seven and reports success.

HOW THIS TEST CAN FAIL: the node cases below run the real rules. A plan that
drops the containers it could not find, a message that reports success for a
group that changed nothing, or an empty pick treated as an empty group is red.

COUNTER-CHECK (2026-09-23): red before - there was no bar, no script and no
translation key; the section could not act on a group at all.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECTION = ROOT / "app" / "templates" / "_server_selection.html"

KEYS = ("web.server.bulk_group", "web.server.bulk_apply", "web.server.bulk_remove",
        "web.server.bulk_applied", "web.server.bulk_not_on_page",
        "web.server.bulk_nothing", "web.server.bulk_pick_group",
        "web.server.bulk_hint")


def test_the_bar_is_in_the_container_section():
    """The gap was here, not on a page of its own."""
    section = SECTION.read_text(encoding="utf-8")

    assert 'id="bulk-group"' in section, "the container table has no group picker"
    assert "web.server.bulk_apply" in section
    assert "web.server.bulk_remove" in section


def test_the_bar_offers_the_four_permissions():
    """Applying only the Active flag would leave 4 boxes per row to tick, which
    is the work this exists to remove."""
    section = SECTION.read_text(encoding="utf-8")

    for action in ("status", "start", "stop", "restart"):
        assert f'id="bulk-allow-{action}"' in section, action


def test_the_script_is_loaded():
    scripts = (ROOT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")

    assert "group_bulk.js" in scripts, "the bar's script is never loaded"


def test_the_bar_reads_the_operators_groups_and_not_the_compose_label():
    """The operator said his own groupings, explicitly not Compose stacks."""
    js = (ROOT / "app" / "static" / "js" / "group_bulk.js").read_text(encoding="utf-8")

    assert "'/api/groups'" in js, "the bar does not ask for the operator's groups"
    # The FIELD, not the word: the file says in its header that it deliberately
    # does not use the Compose label, and a first version of this test failed on
    # its own explanation.
    assert "compose_project" not in js and "composeProject" not in js, \
        "the bar reads the Compose label after all"


def test_it_fills_the_form_rather_than_saving_by_itself():
    """Counter-check on the design: a bar that saved on its own could apply to
    half a group and leave the page showing the other half."""
    js = (ROOT / "app" / "static" / "js" / "group_bulk.js").read_text(encoding="utf-8")

    assert "selected_servers" in js, "it does not touch the Active checkbox"
    # Built per row as allow_<action>_<container>, which is what the form calls
    # them; the four action names are listed right beside it.
    assert "allow_${action}_${name}" in js, "it does not touch the permission checkboxes"
    assert "'status', 'start', 'stop', 'restart'" in js
    assert "/save" not in js and "method: 'POST'" not in js, "the bar saves by itself"


@pytest.mark.parametrize("language", ["en", "de"])
def test_every_text_exists_in_the_catalogue(language):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    missing = [key for key in KEYS if not catalogue.get(key)]

    assert missing == [], f"{language}.json has no text for {missing}"


def test_every_locale_has_the_keys():
    """A web string needs a key in every catalogue. meta.json is not one."""
    locales = [p for p in (ROOT / "locales").glob("*.json") if p.name != "meta.json"]

    assert len(locales) >= 40
    for path in locales:
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in KEYS if key not in catalogue]
        assert missing == [], (path.name, missing)


def test_the_german_texts_are_really_german():
    """Counter-check: copying English into de.json would pass the test above."""
    german = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    english = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))

    same = [key for key in KEYS if german[key] == english[key]]

    assert same == [], f"these are still the English texts: {same}"


def test_the_rules_hold_in_node():
    """The real check: the plan and the message, run as the browser runs them."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/group_bulk.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "group_bulk.test.js")],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 8, result.stdout


# --- What the operator saw on 2026-09-23: "does not look perfect yet" -------


def test_the_remove_button_does_not_sound_like_stopping_containers():
    """THE WORST THING ON THE BAR, and it was not the looks.

    The old wording said "switch the group off". Next to a table of 26 running
    containers that reads as "stop them". It does nothing of the kind: it
    unticks Active and clears the four permission boxes IN THE FORM, and saves
    nothing at all. The operator picked the new wording on 2026-09-23 - it now
    says the control takes the group out of the selection.

    The KEY name stays web.server.bulk_remove, so group_bulk.js and the rest of
    this file are untouched - only the text behind it changed.
    """
    import json

    for language in ("en", "de"):
        text = json.loads((ROOT / "locales" / f"{language}.json").read_text(
            encoding="utf-8"))["web.server.bulk_remove"].lower()
        for forbidden in ("abschalt", "stopp", "switch off", "turn off", "stop "):
            assert forbidden not in text, (language, text)


def test_the_remove_button_can_actually_be_read():
    """MEASURED, not taste: btn-outline-secondary is #6c757d on the card's
    #1E2125, which is 3.45:1 - under the 4.5:1 a normal text needs. That is the
    "washed out" the operator saw. btn-outline-warning is 9.91:1."""
    section = SECTION.read_text(encoding="utf-8")
    position = section.index('id="bulk-remove-btn"')
    button = section[section.rindex("<button", 0, position):position]

    assert "btn-outline-secondary" not in button, (
        "the button that takes permissions away is drawn at 3.45:1 on this "
        "background, which is under the readable minimum")


def test_applying_does_not_silently_strip_the_other_permissions():
    """THE TRAP UNDERNEATH THE LOOKS: apply() sets every box to
    `active && wanted(action)`, so a bar that ships with only Status ticked
    REMOVES start, stop and restart from the whole group on the first press -
    and said so in the last clause of a hint below the buttons.

    All four ship ticked now, and the subtraction is stated where the boxes
    are, not in a footnote.
    """
    section = SECTION.read_text(encoding="utf-8")

    for action in ("status", "start", "stop", "restart"):
        position = section.index(f'id="bulk-allow-{action}"')
        box = section[section.rindex("<input", 0, position):section.index(">", position)]
        assert "checked" in box, f"{action} does not ship ticked - applying would remove it"

    assert "web.server.bulk_permissions_legend" in section, (
        "nothing beside the boxes says that unticked means removed")


def test_the_result_message_is_announced():
    """The only feedback a bulk apply gives, and it was silent to a screen
    reader. The attributes go on a WRAPPER: group_bulk.js assigns
    line.className wholesale, so anything put on the message div itself is
    wiped by the first message it shows."""
    section = SECTION.read_text(encoding="utf-8")
    position = section.index('id="bulk-group-message"')
    wrapper = section[max(0, position - 300):position]

    assert 'role="status"' in wrapper and 'aria-live="polite"' in wrapper, (
        "the bulk result is announced to nobody, and putting the attributes on "
        "the message div itself would be wiped by group_bulk.js")
