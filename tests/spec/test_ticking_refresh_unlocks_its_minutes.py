# -*- coding: utf-8 -*-
"""Ticking Refresh or Recreate in a saved channel row unlocks its minutes.

THE FINDING (audit 2026-09-26): _permissions_table.html renders a saved row's
interval and inactivity fields `disabled` while their box is unticked. The
listeners that unlock them were attached only to rows added with the + button
(config-ui.js initializeCheckboxHandlers). The page-wide handler that once
covered saved rows lived in panel.js, bound to #command-permissions-table - a
table that no longer exists - so for a channel already saved, ticking the box
left the field locked, and the save sent the stale value (usually 1 minute).

THE CONTRACT: one delegated handler on the document, so a saved row and an
added row behave the same (tests/js/minutes_unlock.test.js runs it in node).

HOW THIS TEST CAN FAIL: the handler goes back to being per added row.

COUNTER-CHECK (2026-09-26): red before the fix - node: three of four cases,
"true !== false" for the saved row.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_unlock_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/minutes_unlock.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "minutes_unlock.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 4, result.stdout


def test_the_template_still_locks_an_unticked_row():
    """The premise of the finding: without the disabled attribute there is
    nothing to unlock, and the node cases would test a situation that does
    not occur."""
    markup = (ROOT / "app" / "templates" / "_permissions_table.html").read_text(encoding="utf-8")

    assert "{% if not is_ar_checked %}disabled{% endif %}" in markup
    assert "{% if not is_ri_checked %}disabled{% endif %}" in markup
