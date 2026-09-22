# -*- coding: utf-8 -*-
"""The rule editor sends container-state rules as such - and keeps them on edit.

Found while adding the watchdog's trigger type (Phase 4a, part 5): the editor
built every rule as a message rule. Opening a container-state rule in the
panel and pressing Save silently turned it into a message rule without
keywords - a rule that never fires again, with nothing to say so.

The editor is JavaScript, so the behaviour is checked by running
app/static/js/auto_actions.js in node against a small stand-in DOM
(tests/js/auto_actions_rule_form.test.js): a new container-state rule is sent
with its states, watched containers and restart settings; no ticked container
means all of them; an edited container-state rule stays one; a message rule is
sent exactly as before.

Where node is missing (the production image the test runner uses has none)
this test is SKIPPED, not passed - the GitHub CI runners have node, so it runs
in the gate. Run it by hand with: node tests/js/auto_actions_rule_form.test.js

COUNTER-CHECK (2026-09-22): three cases red before the change; removing the
line that restores the trigger type on edit turns the edit case red.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_rule_editor_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/auto_actions_rule_form.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "auto_actions_rule_form.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok     ") == 5, result.stdout


def test_the_template_offers_both_trigger_types():
    template = (ROOT / "app" / "templates" / "_auto_actions_modal.html").read_text(encoding="utf-8")
    for needle in ('id="aasRuleTriggerType"', 'value="container_state"', 'id="aasContainerTriggerFields"',
                   'id="aasMessageTriggerFields"', 'class="form-check-input aas-state-checkbox"',
                   'id="aasRuleRestartThreshold"', 'id="aasRuleRestartWindow"',
                   'value="high_cpu"', 'value="high_memory"', 'id="aasRuleCpuThreshold"',
                   'id="aasRuleMemoryThreshold"', 'id="aasRuleResourceMinutes"'):
        assert needle in template, needle
