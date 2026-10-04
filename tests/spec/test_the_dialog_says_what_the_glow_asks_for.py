# -*- coding: utf-8 -*-
"""The info dialog says what the glowing Info button asks for, and marks the field.

THE OPERATOR (2026-10-04): Satisfactory's Info button glowed - "but when I
click it I do not know why". The glow means: the player count is on, the
protocol needs a token (Satisfactory app token, Palworld admin password) and
none is set. The dialog said nothing of it.

THE CONTRACT: under the same condition the dialog shows a hint at its top
naming the field, and the field glows like the button; typing a token or
choosing a protocol without one clears both at once
(tests/js/token_needed_mark.test.js runs it in node).

HOW THIS TEST CAN FAIL: the dialog opens silent on a glowing button again, or
keeps the mark after the token is in.

COUNTER-CHECK (2026-10-04): red before the change (node: no hint, no mark).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_dialog_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/token_needed_mark.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "token_needed_mark.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 3, result.stdout


def test_the_page_carries_the_hint_and_the_glow():
    markup = (ROOT / "app/templates/_server_selection.html").read_text(encoding="utf-8")
    assert 'id="modal-query-needs-config"' in markup
    assert "_t('web.server.query_token_missing')" in markup
    assert ".query-token-needs-config" in markup
