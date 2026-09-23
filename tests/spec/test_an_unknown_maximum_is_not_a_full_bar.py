# -*- coding: utf-8 -*-
"""A maximum the server could not measure is not drawn as a full bar.

THE FINDING: when the mech's progress cannot be read, the services return
Power_max_for_level = None and mech_progress_max = None on purpose - nothing
is invented, and tests/spec/test_a_failed_lookup_is_not_full_progress.py pins
that. The panel then divided by it: in JavaScript 5 / null is Infinity, and
Math.min(100, Infinity) is 100. So the very failure the Python side refuses
to guess about was drawn as a FULL power bar and a FULL evolution bar - the
most flattering possible lie about a mech nobody could read.

The width is computed in one place now, which answers "unknown" for a
maximum that is missing or zero, and the panel then shows an empty bar with
a title saying the value could not be read.

REVISITED 2026-09-23: this checked that _scripts.html loads progress_bars.js.
That WAS the place, and it was the wrong place - _scripts.html is included at
the very bottom of config.html, about 800 lines after the inline code that
calls barWidth, so whether the helper existed in time was a race. It now loads
at the top of config.html, and the order is pinned in
tests/spec/test_the_mech_panel_can_draw_its_bars_at_once.py. This still asks
the same question - is the file loaded at all - and asks it where the tag is.

COUNTER-CHECK (2026-09-22): the node cases are red against the old
expression - `Math.min(100, (5 / null) * 100)` is 100.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (ROOT / "app" / "templates" / "config.html").read_text(encoding="utf-8")


def test_the_width_rule_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/progress_bars.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "progress_bars.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok     ") == 6, result.stdout


def test_the_panel_uses_it_for_both_bars():
    assert TEMPLATE.count("barWidth(") >= 2, "the bars still divide on their own"
    assert "Math.min(100, percentage)" not in TEMPLATE


def test_the_panel_loads_the_file():
    """In config.html, not _scripts.html - see the revisit note above."""
    assert "js/progress_bars.js" in TEMPLATE
