# -*- coding: utf-8 -*-
"""Channel translation is not folded away; it loads with the page.

THE REQUEST (operator, 2026-09-26): "the translation function is collapsed by
default, and since we split the web panel that makes no sense any more." The
card was folded from the days of one long settings page, and its languages,
pairs and settings were loaded only on the first unfold - on a tab of its own
that only hid the feature and its state.

HOW THIS TEST CAN FAIL: the card folds again, or its data waits for an unfold.

COUNTER-CHECK (2026-09-26): red before - the card carried class "collapse",
and node saw only the settings request at page load, not languages or pairs.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_card_is_not_collapsed():
    markup = (ROOT / "app" / "templates" / "_channel_translation_settings.html").read_text(encoding="utf-8")

    assert 'id="ctSection"' in markup
    assert not re.search(r'class="collapse"[^>]*id="ctSection"|id="ctCollapseSection"', markup)
    assert 'href="#ctCollapseSection"' not in markup


def test_it_loads_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/channel_translation_loads.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "channel_translation_loads.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 2, result.stdout
