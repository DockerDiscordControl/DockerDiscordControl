# -*- coding: utf-8 -*-
"""The rule editor offers the groups, so nobody has to type "group:".

A rule can name a group since test_a_rule_can_use_a_group.py - as the
containers it watches, and as the containers it acts on. The editor has one
list of checkboxes serving both, so the groups belong in that list. Without
this the feature exists only for someone who knows the prefix, which is the
half-built state the operator complained about.

What this pins:

* the editor loads the groups and offers them as checkboxes whose value is
  "group:<name>" - the form of the saved rule;
* they are marked as groups, with the number of containers, so nobody mistakes
  one for a container;
* the groups come first, and the containers keep their own list;
* a rule that was saved with a group ticks that box again when it is reopened.

COUNTER-CHECK (2026-09-23): red before - auto_actions.js never asked
/api/groups and the only checkboxes were containers.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "app" / "static" / "js" / "auto_actions.js").read_text(encoding="utf-8")
# The list itself is built in rule_targets.js since 2026-09-23 (it also keeps a
# target whose checkbox is gone; see test_a_rule_does_not_widen_itself.py).
TARGETS = (ROOT / "app" / "static" / "js" / "rule_targets.js").read_text(encoding="utf-8")


def test_the_editor_loads_the_groups():
    assert "/api/groups" in JS, "the rule editor never asks for the operator's groups"


def test_a_group_checkbox_carries_the_prefix_the_rule_needs():
    # The value the checkbox carries is what lands in the rule, and the rule
    # resolves "group:<name>" (services/automation/automation_service.py).
    assert "'group:' + group.name" in TARGETS, (
        "a ticked group would be saved as a container name")


def test_the_groups_are_marked_as_groups():
    assert "aas-group-checkbox" in JS, "groups and containers cannot be told apart"


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_heading_exists_in_the_catalogue(language):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    # js.*, not web.*: the JS t() helper is served the js.* keys without their
    # prefix (services/web/i18n_service.py), and a web.* key would render blank.
    assert catalogue.get("js.aas.groups_heading"), f"{language}.json has no heading for them"


def test_reopening_a_rule_ticks_the_group_again():
    """The checkbox is drawn ticked, from the rule itself."""
    assert "checked: (ticked || []).includes(value)" in TARGETS, (
        "a saved group rule opens with nothing ticked")
    assert "renderTargetCheckboxes(document.getElementById(" in JS, (
        "reopening a rule does not redraw the list from the rule")


def test_saving_a_rule_collects_the_ticked_groups():
    """Counter-check: ticking is worth nothing if saving ignores them."""
    collected = JS.split("const containers = Array.from")[1][:200]

    assert "aas-group-checkbox:checked" in collected, "a ticked group is not saved"
