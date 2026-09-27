# -*- coding: utf-8 -*-
"""A provider's own field hides when another provider is chosen.

THE OPERATOR'S SCREENSHOT (2026-09-27) shows "Azure region (Microsoft)" with
DeepL selected. The field was hidden with style.display = 'none' - and its
column carries Bootstrap's d-flex, which sets display with !important, so the
inline style lost. The DeepL tier column had the same class and the same
code: it never hid for Google or Microsoft either.

HOW THIS TEST CAN FAIL: it reads the switch function; hiding must go through
the d-none class (which is !important too and wins by coming later), not the
inline style, for both columns.

COUNTER-CHECK (2026-09-27): red before - both columns used style.display.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_both_provider_columns_hide_by_class():
    script = (ROOT / "app" / "static" / "js" / "channel_translation.js").read_text(encoding="utf-8")
    body = re.search(r"function updateDeeplTierVisibility\(\) \{(.*?)\n\}", script, re.S).group(1)
    assert "style.display" not in body, "an inline display loses against d-flex !important"
    assert body.count("classList.toggle('d-none'") == 2, body


def test_the_region_column_starts_hidden_by_class():
    markup = (ROOT / "app" / "templates" / "_channel_translation_settings.html").read_text(encoding="utf-8")
    tag = re.search(r'<div[^>]*id="ctMsRegionGroup"[^>]*>', markup).group(0)
    assert "d-none" in tag and "display: none" not in tag, tag
