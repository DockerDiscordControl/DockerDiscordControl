# -*- coding: utf-8 -*-
"""The info dialog's "announce player joins" box reads and writes its hidden field.

THE OPERATOR (2026-10-04): join notices are settable per container in the web
panel (tests/spec/test_join_notices_are_chosen_per_container.py holds the
saving and the join check). This holds the dialog: tests/js/
join_notice_setting.test.js runs config-ui.js in node - a saved "0" opens
unticked, a container without a value opens ticked, saving writes the box
back.

HOW THIS TEST CAN FAIL: the box is not filled or not written back.

COUNTER-CHECK (2026-10-04): red before the change (node: the box stayed
untouched, the field kept its value).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_dialog_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/join_notice_setting.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "join_notice_setting.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 3, result.stdout
