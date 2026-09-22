# -*- coding: utf-8 -*-
"""The cooldown manager has no hook that pretends to enforce something.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (review C61, section 19 F3): ``before_invoke_check()`` returns a
closure named ``check_cooldown`` that reads the command name and the user id,
builds ``command_key = f"{command_name}:{user_id}"`` - and then returns True,
always, whatever that key says. Its own comment admitted it: "This is a
simplified check - in production you'd implement proper cooldown tracking".

Nothing registers it. The real enforcement is `apply_dynamic_cooldowns`,
which puts a `commands.CooldownMapping` into each command's `_buckets` and
lets py-cord do the counting. What was left is a method shaped like a
`bot.before_invoke` guard, so the next person to wire it up would install a
check that permits everything - and the two tests it had only confirmed that
it returns True.

The method and its unused key go.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
MODULE = PROJECT / "services" / "infrastructure" / "dynamic_cooldown_manager.py"
SOURCE_DIRECTORIES = ("cogs", "services", "app", "utils")


def _method_names():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    return [node.name
            for cls in tree.body if isinstance(cls, ast.ClassDef)
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")]


def _names_used(source: str) -> set:
    """Names the code actually reads, from the syntax tree.

    Not a text search: a first version of this scan looked for the name in the
    raw file text, so the comment left behind where the dead method used to
    be counted as a use of it - the scan had blinded itself, and the mutation
    that put the method back went unnoticed.

    A `def foo` produces a FunctionDef node, not a Name, so a definition does
    not count as a use of itself. A call from a wrapper in the same module
    does.
    """
    used = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                used.add(alias.asname or alias.name.split(".")[0])
    return used


def _mentioned_anywhere():
    mentioned = set()
    for directory in SOURCE_DIRECTORIES:
        for path in (PROJECT / directory).rglob("*.py"):
            mentioned |= _names_used(path.read_text(encoding="utf-8"))
    return mentioned


def _unused(defined, mentioned):
    return sorted(name for name in defined if name not in mentioned)


def test_the_module_still_has_methods():
    """Guard against a blunt test: an empty class would pass trivially."""
    assert len(_method_names()) >= 2, _method_names()


def test_the_scan_can_tell_used_from_unused():
    """Guard against a blunt tool: with nothing dead left, a blinded scan
    would find nothing either."""
    assert _unused(["kept", "orphan"], {"kept", "something_else"}) == ["orphan"]


def test_a_method_called_from_its_own_module_counts_as_used():
    """`apply_dynamic_cooldowns` is called by the module-level wrapper that
    app/bot/dependencies.py imports - that is a use, not a definition."""
    source = ("class C:\n    def used(self):\n        pass\n"
              "    def never(self):\n        pass\n\n"
              "def wrapper(c):\n    return c.used()\n")

    used = _names_used(source)

    assert "used" in used
    assert "never" not in used


def test_a_name_in_a_comment_is_not_a_use():
    """BLINDNESS GUARD: the comment that says what was removed must not keep
    the scan from noticing it coming back."""
    source = "# never() stood here and did nothing\nclass C:\n    def never(self):\n        pass\n"

    assert "never" not in _names_used(source)


def test_every_public_method_is_used():
    unused = _unused(_method_names(), _mentioned_anywhere())

    assert not unused, (
        "nothing in the application uses these, so they enforce nothing - and a "
        f"hook that always says yes is worse than no hook: {unused}"
    )
