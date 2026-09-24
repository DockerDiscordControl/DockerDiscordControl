# -*- coding: utf-8 -*-
"""No test may be written so that nothing can make it red.

THE FINDING (2026-09-24). Of 5,916 test functions, 87 make no assertion at all
- not directly, not through a helper in their own file, not through
pytest.raises and not through a mock's assert_*. Most are the honest "this must
not raise" shape: the call IS the check, and an exception fails the test.

One was not. tests/unit/extended/test_services_gaps.py had:

    try:
        task._calculate_next_donation_run()
    except Exception:
        pass
    # Test exercised the error path; final state may vary

It passed whether the code worked, raised, or was deleted. Its own last line
admits it. And the mock it used made the case even emptier than it looks: the
scheduler was handed a MagicMock as its timezone, `datetime.now(tz)` on a
non-tzinfo raises TypeError, the code does not catch TypeError - so the
fallback the case was named after was never reached at all. The TypeError went
straight into that `except Exception: pass`.

It is now three cases with a real timezone whose localize() fails on demand,
one per level the code actually has: the 2nd Sunday, the 10th of next month,
and 30 days out. Counter-checked by sabotaging each fallback in scheduler.py
on a green baseline.

WHAT THIS PINS: no assertion of any kind AND an `except ...: pass` - which is
exactly "nothing can make this red". The count of tests that assert nothing at
all is kept as a budget beside it, in the idiom this project already uses for
the German lines: it may shrink and never grow. A new "must not raise" test is
fine; it just has to be counted, so the shape stays a decision rather than a
habit.

HOW THIS TEST CAN FAIL: writing a test that swallows the exception it was
meant to catch, or adding assertion-free tests past the budget.

COUNTER-CHECK (2026-09-24): red before, naming
test_calculate_next_donation_run_falls_back.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"

# Tests that make no assertion at all. ONLY EVER SHRINK THIS.
# Measured 2026-09-24, after the donation-fallback case was rewritten.
ASSERTION_FREE_BUDGET = 86


def _asserting_helpers(tree):
    """Functions in the same file that assert, so a test may delegate to one."""
    return {node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("test_")
            and any(isinstance(inner, ast.Assert) for inner in ast.walk(node))}


def _checks_something(function, helpers):
    """Every way a test in this project states an expectation."""
    if any(isinstance(node, ast.Assert) for node in ast.walk(function)):
        return True
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            called = ast.unparse(node.func)
            if "raises" in called or ".assert_" in called:
                return True
            if called.split(".")[-1] in helpers:
                return True
    return "pytest.fail" in ast.unparse(function)


def _survey():
    """(tests that check nothing, tests that also swallow their exceptions)."""
    silent, unfailable = [], []
    for path in sorted(TESTS.rglob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        helpers = _asserting_helpers(tree)
        for function in [node for node in ast.walk(tree)
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and node.name.startswith("test_")]:
            if _checks_something(function, helpers):
                continue
            where = f"{path.relative_to(ROOT)}::{function.name}"
            silent.append(where)
            for block in [node for node in ast.walk(function) if isinstance(node, ast.Try)]:
                for handler in block.handlers:
                    if all(isinstance(statement, ast.Pass) for statement in handler.body):
                        unfailable.append(f"{where} (line {handler.lineno})")
    return silent, unfailable


def test_the_scan_sees_the_suite():
    """Safeguard against a blunt tool: a scan parsing nothing is green."""
    counted = sum(1 for path in TESTS.rglob("test_*.py"))

    assert counted > 300, f"only {counted} test files found - wrong path?"


def test_no_test_swallows_the_thing_it_was_written_to_catch():
    """THE FINDING: a test that asserts nothing and catches everything passes
    whether the code works, raises, or is deleted."""
    _silent, unfailable = _survey()

    assert unfailable == [], (
        f"{len(unfailable)} test(s) can never fail - no assertion, and the "
        f"exception is swallowed:\n  " + "\n  ".join(unfailable))


def test_the_assertion_free_tests_do_not_multiply():
    """A budget, not a target. "It must not raise" is a real check - the call
    is the assertion - but it is the weakest one available, and a suite drifting
    towards it gets quieter without anyone deciding to make it quieter."""
    silent, _unfailable = _survey()

    assert len(silent) <= ASSERTION_FREE_BUDGET, (
        f"{len(silent)} tests assert nothing, the budget is "
        f"{ASSERTION_FREE_BUDGET}. New ones since:\n  "
        + "\n  ".join(silent[-5:]))
