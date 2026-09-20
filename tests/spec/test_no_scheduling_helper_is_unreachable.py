# -*- coding: utf-8 -*-
"""Nothing in the scheduling helpers pretends to guard a path nobody walks.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage C, section 25 F2, re-checked 2026-09-20):
``check_schedule_permissions`` is named like a permission check and answers
only from the container's ``allowed_actions`` - it never looks at the channel
the request came from, so by its own name it would let a status channel
create tasks. It cannot: nothing calls it. Its only caller was
``cogs/scheduler_commands.py``, the slash commands removed in review B17.

The same is true of four of its neighbours in that module. What is left is a
file of helpers that look like the scheduling API and are wired to nothing -
the next person to use one gets a "permission check" that checks no
permission.

The live path asks properly: the task buttons in
``status_info_integration.py`` and ``control_ui.py`` require the channel's
``schedule`` permission or a registered admin (SPEC.md Z5, B2, reviews B3 and
B27), and the web panel has its own login.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
MODULE = PROJECT / "services" / "scheduling" / "schedule_helpers.py"
SOURCE_DIRECTORIES = ("cogs", "services", "app", "utils")
DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _defined_names():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    return [node.name for node in tree.body if isinstance(node, DEFINITIONS)]


def _used_elsewhere():
    """Everything the application code outside this module mentions."""
    mentioned = set()
    for directory in SOURCE_DIRECTORIES:
        for path in (PROJECT / directory).rglob("*.py"):
            if path == MODULE:
                continue
            mentioned.update(re.findall(r"[A-Za-z_]\w*", path.read_text(encoding="utf-8")))
    return mentioned


def _unused(defined, mentioned):
    return sorted(name for name in defined if name not in mentioned)


def test_the_module_still_has_helpers():
    """Guard against a blunt test: an empty module would pass trivially."""
    assert len(_defined_names()) >= 2, _defined_names()


def test_the_scan_can_tell_used_from_unused():
    """Guard against a blunt tool - a mutation that blinded it went unnoticed
    once, because with no dead helper left there was nothing for it to miss."""
    assert _unused(["kept", "orphan"], {"kept", "something_else"}) == ["orphan"]


def test_every_helper_is_used():
    unused = _unused(_defined_names(), _used_elsewhere())

    assert not unused, (
        "nothing in the application calls these, so they cannot guard anything: "
        f"{unused}"
    )
