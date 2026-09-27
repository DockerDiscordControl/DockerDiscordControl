# -*- coding: utf-8 -*-
"""CI installs node, so the panel's JavaScript tests run there too.

THE FINDING (2026-09-27): every tests/js file runs through a spec wrapper that
skips when node is missing - right for the test container, which has no node.
The CI workflow had no node either, so all 26 wrappers skipped there, silently:
the nav highlighting, the id escaping, the help lines and the rest were checked
only on the developer's Mac. And a change to app/static or app/templates alone
did not start the workflow at all.

HOW THIS TEST CAN FAIL: it reads the workflow; node must be set up in the job
that runs the specs, and scripts and templates must be in the path filters.

COUNTER-CHECK (2026-09-27): red before - no setup-node, neither path filtered.
"""

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "tests.yml"


def test_node_is_set_up():
    assert re.search(r"uses:\s*actions/setup-node@", WORKFLOW.read_text(encoding="utf-8"))


def test_scripts_and_templates_start_the_workflow():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("'app/static/**'") == 2 and text.count("'app/templates/**'") == 2
