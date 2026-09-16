# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Audit 2026-09 package A regression tests       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Task UI buttons must not submit the surrounding #config-form (audit 2026-09 A11)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("relative_path", [
    "app/templates/tasks/list.html",
    "app/templates/tasks/form.html",
    "app/static/js/tasks.js",
])
def test_task_buttons_have_type_button(relative_path):
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    buttons = re.findall(r"<button\b[^>]*>", source)
    assert buttons, f"no buttons found in {relative_path}"
    for tag in buttons:
        assert 'type="button"' in tag, f"{relative_path}: {tag}"
