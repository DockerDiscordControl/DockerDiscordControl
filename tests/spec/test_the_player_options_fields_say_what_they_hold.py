# -*- coding: utf-8 -*-
"""The player-option fields send what they show (v3.1.0, app/static/js/player_options.js).

The task form, the task edit dialog and the rule editor share three fields:
"only when nobody plays", the longest wait, and the warning before. The server
checks the values again (player_gate.normalize_options); this checks that the
page sends them at all, sends nothing for a start, shows the block for restart
and stop only, and clears the fields when an edited task has no options.

HOW THIS TEST CAN FAIL: tests/js/player_options.test.js in node - seven cases.
Skipped where node is missing (the test image); CI and the Mac run it.

COUNTER-CHECK (2026-09-28): with readPlayerOptions ignoring the action, the
"a start sends no options" case went red.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_page_loads_the_helper():
    assert "player_options.js" in (ROOT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")


def test_the_fields_behave():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/player_options.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "player_options.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 7, result.stdout
