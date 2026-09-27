# -*- coding: utf-8 -*-
"""A changed translation setting says it is not saved, and leaving asks first.

THE FINDING (translation audit, 2026-09-26, #10): the provider, key, tier,
region, limits and display switches of the channel translation save only
through the section's own button. They are rightly marked data-saves-itself,
so the page's unsaved-changes banner ignores them - and nothing else said
anything; leaving the page lost the change silently.

The behaviour is checked in node (tests/js/translation_unsaved_hint.test.js);
this file runs it where node exists and checks the hint is in the markup.

COUNTER-CHECK (2026-09-27): red before - no hint, no question on leaving.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_hint_is_in_the_markup():
    markup = (ROOT / "app" / "templates" / "_channel_translation_settings.html").read_text(encoding="utf-8")
    assert 'id="ctUnsavedHint"' in markup
    assert "web.lang.unsaved_translation_settings" in markup


def test_it_works_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/translation_unsaved_hint.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "translation_unsaved_hint.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok     ") == 4, result.stdout
