# -*- coding: utf-8 -*-
"""An apostrophe in a group name is a letter, not the end of a script string.

THE FINDING (audit 2026-09-26): the per-admin assignment built each checkbox
handler as onchange="toggleAdminContainer('<id>', '<escaped name>', ...)". The
HTML parser decodes &#039; back to ' before the handler runs, so escaping for
HTML does not protect a JavaScript string inside an attribute. A group named
"Bob's" (group names may hold anything but / \\ and line breaks) turned the
box into a syntax error, and a name like  x',alert(1),'  ran script in the
panel of whoever opened the settings - a stored self-XSS for anybody who can
create groups.

THE CONTRACT: the name travels in a data- attribute, and the handler's source
holds no name at all (tests/js/admin_assignment_names.test.js runs the
renderer in node and reads the handler the way a browser would).

COUNTER-CHECK (2026-09-26): red before the fix - "missing ) after argument
list" for Bob's, and the crafted name put alert( into the handler.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_the_names_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/admin_assignment_names.test.js by hand")
    result = subprocess.run([node, str(ROOT / "tests" / "js" / "admin_assignment_names.test.js")],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 3, result.stdout
