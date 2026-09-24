# -*- coding: utf-8 -*-
"""The spelling that marks a group target is written down once.

THE FINDING (2026-09-24): ``group:`` is how DDC says "this name is a group and
not a container" - in an auto-action rule's targets, in an admin assignment,
in the name a button hands to the action service. It was spelled out in four
Python places, three of them as a constant of their own:

    services/automation/automation_service.py   GROUP_PREFIX = "group:"
    services/docker_service/group_actions.py    GROUP_PREFIX = "group:"
    services/config/group_references.py         GROUP_PREFIX = "group:"
    cogs/group_control.py, app/web/routes.py    f"group:{name}"

Four copies of one word that must agree. Nothing was broken by it today, and
that is exactly when it is cheap to fix: the day one of them changes, the
other three keep writing the old spelling and every group target written by
one half stops being read by the other - silently, because an unknown name is
simply not a group.

IT LIVES WHERE THE GROUP LIVES, in services/config/group_service.py, with the
two questions that always follow it: is this name a group, and what is the
group called. Everybody else imports them.

THE TWO IN JAVASCRIPT STAY, and that is a decision rather than drift. The
panel loads its scripts in a fixed order and there is no module system to hang
a shared constant on; config-ui.js is loaded before rule_targets.js, so
neither can read a constant from the other. They are listed here by name, so a
third copy is noticed.

HOW THIS TEST CAN FAIL: a fifth place spelling it out, or a module keeping its
own constant instead of importing the one.

COUNTER-CHECK (2026-09-24): red before, naming all four Python places.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
HOME = PROJECT / "services" / "config" / "group_service.py"
SOURCES = ("cogs", "services", "app", "utils")

# The literal as CODE uses it: the exact string, or an f-string building it.
# Prose in a docstring says "group:<name>", which is not a second definition -
# the first version of this scan flagged six of those and would have taught
# whoever read it to ignore the result.
SPELLED = re.compile(r"""["']group:["']|group:\{""")

# The panel's two, kept because the page has no module system and its scripts
# are loaded in a fixed order - neither file can read a constant from the
# other. ONLY EVER SHRINK THIS.
JAVASCRIPT_COPIES = {
    "app/static/js/rule_targets.js",
    "app/static/js/config-ui.js",
}


def _python_files():
    for root in SOURCES:
        for path in sorted((PROJECT / root).rglob("*.py")):
            yield path


def test_the_home_has_the_spelling_and_the_questions():
    source = HOME.read_text(encoding="utf-8")

    assert re.search(r'^GROUP_PREFIX\s*=\s*"group:"', source, re.M), (
        "the group's own module does not define the spelling")
    for helper in ("def is_group_target", "def group_name_of", "def group_target"):
        assert helper in source, helper


def test_nobody_else_spells_it_out():
    """THE FINDING: four copies of one word that must agree."""
    offenders = []
    for path in _python_files():
        if path == HOME:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        # A test fixture or a docstring naming an example group is not a
        # second definition; only code that BUILDS or MATCHES the prefix is.
        for match in SPELLED.finditer(source):
            line = source[:match.start()].count("\n") + 1
            text = source.splitlines()[line - 1]
            if text.lstrip().startswith("#"):
                continue
            offenders.append(f"{path.relative_to(PROJECT).as_posix()}:{line} {text.strip()[:60]}")

    assert offenders == [], (
        "these spell the group prefix themselves instead of importing it from "
        "services/config/group_service.py:\n  " + "\n  ".join(offenders))


def test_no_module_keeps_a_second_constant():
    """A copy that agrees today is still a copy."""
    own = []
    for path in _python_files():
        if path == HOME:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"^GROUP_PREFIX\s*=\s*(.+)$", source, re.M):
            if "group_service" not in match.group(1):
                own.append(path.relative_to(PROJECT).as_posix())

    assert own == [], f"these define their own GROUP_PREFIX: {own}"


def test_the_javascript_copies_are_the_known_two():
    """Listed rather than swept: the page has no module system, and a third
    copy is a decision somebody has to make on purpose."""
    found = set()
    for path in sorted((PROJECT / "app" / "static" / "js").rglob("*.js")):
        source = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
        if SPELLED.search(source):
            found.add(path.relative_to(PROJECT).as_posix())

    assert found == JAVASCRIPT_COPIES, (
        f"the scripts that spell the prefix changed: {sorted(found)}")


def test_the_helpers_answer_the_two_questions():
    """Counter-check on the move: the behaviour is what it was."""
    from services.config.group_service import (GROUP_PREFIX, group_name_of,
                                               group_target, is_group_target)

    assert GROUP_PREFIX == "group:"
    assert is_group_target("group:Gameserver") is True
    assert is_group_target("Gameserver") is False
    assert is_group_target(None) is False
    assert group_name_of("group:Gameserver") == "Gameserver"
    assert group_name_of("Gameserver") == "Gameserver", (
        "a plain container name must come back unchanged")
    assert group_target("Gameserver") == "group:Gameserver"
