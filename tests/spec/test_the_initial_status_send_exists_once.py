# -*- coding: utf-8 -*-
"""The delayed initial status send is written down exactly once.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 04 F4, re-checked 2026-09-20):
``DockerControlCog.send_initial_status_after_delay_and_ready`` did the same
three steps as the closure ``send_initial_after_delay`` that
``_setup_background_loops`` actually schedules: wait for the bot, sleep,
``send_initial_status()``. Its own log line says "from __init__ after delay"
- the caller it was written for. That caller is gone: nothing in the
repository, tests included, ever called the method. What stayed behind was a
second way to start the initial send, past ``_cancel_existing_loops()`` and
past the ``_background_loops_started`` guard - so a future caller would post
a second set of overview messages whose ids the cog does not track.

Nothing else in this file would have caught it: a method with no callers is
green in every test there is.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "cogs" / "docker_control.py"
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _calls(function):
    """Every name called in ``function`` itself - not in a function nested in it.

    A closure defined inside a function would otherwise be counted twice: once
    for itself and once for the function it sits in.
    """
    names = set()
    nested = [node for node in ast.walk(function)
              if isinstance(node, FUNCTIONS) and node is not function]
    skip = {id(node) for parent in nested for node in ast.walk(parent)}
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or id(node) in skip:
            continue
        if isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _senders(tree):
    """Functions that wait for the bot, sleep and then send the initial status."""
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, FUNCTIONS):
            continue
        calls = _calls(function)
        if {"wait_until_ready", "sleep", "send_initial_status"} <= calls:
            found.append(f"{function.name} (line {function.lineno})")
    return found


def test_the_module_is_read():
    """Guard against a blunt tool: the file must parse and hold the loop setup."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {node.name for node in ast.walk(tree) if isinstance(node, FUNCTIONS)}
    assert "_setup_background_loops" in names, "the scan is looking at the wrong file"


def test_the_initial_status_send_exists_once():
    senders = _senders(ast.parse(SOURCE.read_text(encoding="utf-8")))
    assert len(senders) == 1, (
        "more than one way to schedule the initial status send, and only one of "
        f"them is the one that runs: {senders}"
    )
