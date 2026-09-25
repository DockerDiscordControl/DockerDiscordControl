# -*- coding: utf-8 -*-
"""No line waits behind an await that can never return.

FOUND WHILE READING THE STARTUP LOG for the operator. One line announces
something and is never answered:

    ddc.docker_control - INFO - Starting MechStatusCacheService background loop...

No "started successfully", no failure. The code says both should be possible:

    logger.info("Starting MechStatusCacheService background loop...")
    await self.mech_status_cache_service.start_background_loop()
    logger.info("MechStatusCacheService background loop started successfully")

THE SECOND LINE CANNOT RUN. start_background_loop() does not start a loop and
return - it IS the loop: `while self._loop_running:` with the refresh inside,
and `self._loop_task = asyncio.current_task()` so the caller's task can be
cancelled later. Awaiting it therefore never comes back. The success line has
been unreachable since the day it was written, and its absence looked exactly
like a failure that was never reported.

AND IT ONLY BECAME VISIBLE TODAY. Until 6375c2af the service logged under
services.mech.mech_status_cache_service, a name no handler listened to, so its
own "Starting mech status cache loop (interval: 30.0s, TTL: 45.0s)" never
appeared either. The loop had been running perfectly the whole time and
nothing in the log could say so.

THE RULE, and it is worth having for one site because there are six functions
that never return - the token waits, the proxy handler, the client pool queue,
the animation stepper and this one. Awaiting any of them and then writing a
line is a promise that cannot be kept, and the next reader will spend the same
time on it that this one did.

WHAT REPLACES IT: nothing. The service announces itself with its own interval
and TTL, on a logger that now reaches the files, and a failure still raises
into the except clause below. The cog's own announcement drops to DEBUG - two
"starting" lines for one loop, and the service's is the one with the numbers
in it.

HOW THIS TEST CAN FAIL: a statement placed after awaiting one of the six.

COUNTER-CHECK (2026-09-25): red before - one site, in start_mech_cache_loop.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
NOT_APP_CODE = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv", "docs", "scripts"}


def _app_files():
    for path in sorted(PROJECT.rglob("*.py")):
        if NOT_APP_CODE & set(path.relative_to(PROJECT).parts):
            continue
        try:
            yield path.relative_to(PROJECT), ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue


def _functions_that_never_return():
    """Names whose body is an endless loop, so awaiting one never comes back.

    READ FROM THE TREE, not from a list I keep by hand: a while whose test is
    True, or a flag the loop itself owns, with the work inside it. A list
    would go stale exactly like the line this file is about.
    """
    names = {}
    for path, tree in _app_files():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.While):
                    continue
                test = ast.unparse(inner.test)
                if test == "True" or ("self._" in test and "running" in test):
                    names.setdefault(node.name, f"{path}:{node.lineno}")
    return names


def _statement_lists(function):
    for node in ast.walk(function):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                yield block


def _lines_waiting_behind_a_loop():
    endless = _functions_that_never_return()
    for path, tree in _app_files():
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for block in _statement_lists(function):
                for index, statement in enumerate(block[:-1]):
                    for node in ast.walk(statement):
                        if not isinstance(node, ast.Await):
                            continue
                        called = ast.unparse(node.value)
                        for name, where in endless.items():
                            if called.endswith(f"{name}()"):
                                yield (f"{path}:{statement.lineno} in {function.name}(): "
                                       f"awaits {name}() ({where}), then "
                                       f"{ast.unparse(block[index + 1])[:50]}")


def test_no_line_waits_for_a_loop_that_never_ends():
    """THE FINDING: a success message that could never be printed."""
    waiting = sorted(set(_lines_waiting_behind_a_loop()))

    assert waiting == [], (
        "these lines sit behind an await that cannot return, so they read as "
        f"promises the program never keeps: {waiting}")


def test_the_scan_knows_which_functions_never_return():
    """Counter-check, the one ten sabotages have walked past: a scan that finds
    no endless function would pass the case above while proving nothing."""
    endless = _functions_that_never_return()

    assert "start_background_loop" in endless, sorted(endless)
    assert len(endless) >= 4, sorted(endless)


def test_an_ordinary_await_is_not_flagged():
    """The other way. Most awaits DO return, and flagging those would make
    this scan useless - the mistake four earlier scans of mine made."""
    endless = _functions_that_never_return()

    for ordinary in ("get_status", "send", "edit", "fetch_channel"):

        assert ordinary not in endless, f"{ordinary} was called endless"


def test_the_loop_is_still_started_and_failures_still_reported():
    """The opposite mistake: deleting the await with the unreachable line
    would stop the mech cache entirely and say nothing about it."""
    source = (PROJECT / "cogs" / "background_loops.py").read_text(encoding="utf-8")
    starter = next(node for node in ast.walk(ast.parse(source))
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name == "start_mech_cache_loop")
    body = ast.unparse(starter)

    assert "start_background_loop()" in body, "the mech cache is never started"
    assert "logger.error" in body, "a failure to start would pass in silence"
