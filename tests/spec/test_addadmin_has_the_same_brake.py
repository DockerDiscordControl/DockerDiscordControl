# -*- coding: utf-8 -*-
"""/addadmin is slowed down like every other command.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 05 F3, re-checked 2026-09-20):
every slash command of this cog asks ``_check_spam_protection`` before doing
any work - /control, /help, /ping, /donate, /info, /serverstatus. /addadmin
does not. It opens a modal that writes to the admin list, and it could be
re-invoked as fast as Discord's own rate limit allows. The brake exists so
one person cannot flood the bot with work; the command that changes who may
control containers is the last one that should be exempt.
"""

import ast
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "cogs" / "docker_control.py"
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
# The slash commands of this cog, by the name they are registered under.
COMMANDS = ("control", "help_command", "ping_command", "donate_command",
            "info_command", "addadmin")


def _own_calls(function):
    """Calls in the function itself, not in a function nested in it."""
    nested = [node for node in ast.walk(function)
              if isinstance(node, FUNCTIONS) and node is not function]
    skip = {id(node) for parent in nested for node in ast.walk(parent)}
    names = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and id(node) not in skip:
            if isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                names.add(node.func.id)
    return names


def _asks_for_the_brake(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for function in ast.walk(tree):
        if isinstance(function, FUNCTIONS) and function.name == name:
            return "_check_spam_protection" in _own_calls(function)
    raise AssertionError(f"{name} is not in {SOURCE.name} any more")


@pytest.mark.parametrize("command", [c for c in COMMANDS if c != "addadmin"])
def test_the_other_commands_ask_for_the_brake(command):
    """Premise: this is what every sibling does."""
    assert _asks_for_the_brake(command), f"{command} does not ask any more"


def test_addadmin_asks_for_the_brake_too():
    assert _asks_for_the_brake("addadmin"), (
        "the command that changes who may control containers has no brake"
    )
