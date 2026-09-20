# -*- coding: utf-8 -*-
"""Every module under cogs/ can actually be reached by the running bot.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 07, re-checked 2026-09-20):
``cogs/scheduler_commands.py`` holds ``ScheduleCommandsMixin`` with seven
``_impl_schedule_*`` command implementations - and no cog inherits it, the
startup loads three extensions and this is not one of them, and nothing
outside the file imports it. ``docker_control.py`` says why, in its own
words: "TASK COMMANDS REMOVED ... Task scheduling is now handled exclusively
through the UI buttons", including the note that "the following
implementation methods have been removed: all _impl_schedule_* methods".
They were removed there and stayed here. ``cogs/autocomplete_handlers.py``
hung on the same thread: its only importer was that module.

The scan starts at what the bot really loads - the extension list in
``app/bot/startup_steps/commands.py`` plus every cogs module imported from
app, services or utils - and follows the imports from there. What it does
not reach, the bot cannot reach either, however well the module is written
and however many tests it has.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
COGS = PROJECT / "cogs"
OUTSIDE = ("app", "services", "utils")


def _cogs_modules():
    return {path.stem for path in COGS.glob("*.py") if path.stem != "__init__"}


def _mentioned_in(path, relative_to_cogs):
    """cogs modules named by imports - or, outside cogs, by a plain string."""
    found = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.level and relative_to_cogs:
                found.add(node.module.split(".")[0])
            elif node.module.startswith("cogs."):
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("cogs."):
                    found.add(alias.name.split(".")[1])
        elif not relative_to_cogs and isinstance(node, ast.Constant) \
                and isinstance(node.value, str) and node.value.startswith("cogs."):
            # bot.load_extension("cogs.docker_control")
            found.add(node.value.split(".", 1)[1])
    return found


def _roots():
    """What the bot loads or imports from outside the cogs package."""
    roots = set()
    for directory in OUTSIDE:
        for path in (PROJECT / directory).rglob("*.py"):
            roots |= _mentioned_in(path, relative_to_cogs=False)
    return roots


def _reachable():
    modules = _cogs_modules()
    seen, todo = set(), [name for name in _roots() if name in modules]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo += [other for other in _mentioned_in(COGS / f"{name}.py", relative_to_cogs=True)
                 if other in modules]
    return seen


def test_the_scan_finds_the_bots_own_starting_points():
    """Guard against a blunt tool: an empty root set would flag everything."""
    roots = _roots() & _cogs_modules()
    assert "docker_control" in roots, f"the extension list was not read: {sorted(roots)}"


def test_every_cog_module_is_reachable():
    unreachable = sorted(_cogs_modules() - _reachable())
    assert not unreachable, (
        f"the bot never loads these modules, so nothing in them can run: {unreachable}"
    )
