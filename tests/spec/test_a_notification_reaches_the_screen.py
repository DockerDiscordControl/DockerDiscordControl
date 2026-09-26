# -*- coding: utf-8 -*-
"""A notification on the settings page reaches the screen, not the console.

THE FINDING (audit 2026-09-26): mech_panel.js and advanced_settings_modal.js
each declared a global showNotification, and advanced_settings_modal.js loads last of them.
Its body was a console.log. The channel-translation editor
(channel_translation.js ctShowAlert prefers showNotification) and the
auto-action dialog report through it, so "rule saved", "rule deleted" and the
errors that explain why Save did nothing were never shown. The editor's own
visible fallback was never reached, because a showNotification existed.

THE CONTRACT: exactly one showNotification, in config-ui.js, and it puts the
message on the page as text. The node cases run the three scripts in the
order config.html loads them (tests/js/notifications.test.js).

HOW THIS TEST CAN FAIL: a second declaration comes back (the last one loaded
would win again), or the one left does not show anything.

COUNTER-CHECK (2026-09-26): red before the fix - node reported "nothing was
put on the page", and two declarations were found.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "app" / "static" / "js"


def test_there_is_one_show_notification():
    declared = sorted(path.name for path in JS.glob("*.js")
                      if re.search(r"^\s*function\s+showNotification\s*\(",
                                   path.read_text(encoding="utf-8"), re.M))

    assert declared == ["config-ui.js"], declared


def test_the_notification_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/notifications.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "notifications.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 3, result.stdout
