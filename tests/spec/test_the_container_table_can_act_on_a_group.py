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
