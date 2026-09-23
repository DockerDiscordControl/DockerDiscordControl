# -*- coding: utf-8 -*-
"""A rule that loses sight of its group does not start watching everything.

THE FINDING (independent review of the group work, 2026-09-23): the Python
side refuses to turn a deleted group into "no restriction" - an empty trigger
list means every container, so a list of dead groups resolves to nothing
instead (services/automation/automation_service.py). The editor defeated that:

* a rule watching "group:Gameserver" is opened after the group was deleted, or
  after /api/groups failed once (allGroups is then empty and never retried);
* the checkbox does not exist, so the tick is lost;
* a container-state rule is saved BEFORE the "nothing selected" guard, so the
  rule is written with an empty list;
* DDC reads that as EVERY container. A rule written for three containers now
  restarts every unhealthy container on the host, silently.

Two answers, both here: the editor draws its checkboxes from the rule itself,
so a target with no checkbox keeps its tick and is marked "not found"; and
emptying a rule that WAS watching something asks first.

COUNTER-CHECK (2026-09-23): the node cases cover both, and the count below is
what makes a rule quietly disappearing from rule_targets.js fail here.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "app" / "static" / "js" / "auto_actions.js").read_text(encoding="utf-8")


def test_the_rules_hold_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/rule_targets.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "rule_targets.test.js")],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 8, result.stdout


def test_the_editor_draws_from_the_rule():
    assert "renderTargetCheckboxes" in JS, "the editor still builds its own list"
    assert "ticksOfCurrentRule" in JS


def test_emptying_a_watching_rule_asks_first():
    guarded = JS.split("if (isContainerStateRule())")[1][:400]

    assert "saveWidensToEveryContainer" in guarded, (
        "a container-state rule is still saved empty without a word")


def test_the_value_is_escaped_for_an_attribute():
    """escapeHtml leaves the double quote alone; the value sits in an attribute."""
    assert "escapeAttribute" in JS
    assert "&quot;" in JS


def test_the_script_is_loaded_before_the_editor():
    scripts = (ROOT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")

    assert scripts.index("rule_targets.js") < scripts.index("auto_actions.js"), (
        "the editor would call a function that is not there yet")


@pytest.mark.parametrize("key", ["js.aas.target_missing", "js.aas.confirm_widen_to_all"])
@pytest.mark.parametrize("language", ["en", "de"])
def test_the_texts_exist(language, key):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    assert catalogue.get(key), f"{language}.json has no text for {key}"
