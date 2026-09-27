# -*- coding: utf-8 -*-
"""Every dot of the navigation lights up over its section, and points at one.

THE OPERATOR (2026-09-27): the new channel-translation dot "is not
highlighted like the others when I have the section in focus - please check
all nav bar highlighters". floating_nav.js kept its own list of twelve
section ids; the dot added to the bar was not in it. The list now comes from
the bar itself - tests/js/nav_highlight.test.js checks every dot of the real
base.html in node. This file also checks that every dot's target exists in
the templates, since a dot pointing at nothing can never light up either.

COUNTER-CHECK (2026-09-27): red before - the node case named
channel-translation-settings as the one dot that never lit up; all eleven
others lit.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_every_dot_points_at_a_section_that_exists():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    targets = [t for t in re.findall(r'<a href="#([^"]+)" class="nav-dot"', base) if t != "top"]
    markup = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app" / "templates").glob("*.html"))
    missing = [t for t in targets if f'id="{t}"' not in markup]
    assert targets and not missing, f"dots pointing at nothing: {missing}"


def test_every_dot_lights_up_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/nav_highlight.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "nav_highlight.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok     ") == 2, result.stdout
