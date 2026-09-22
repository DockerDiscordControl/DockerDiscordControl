#!/usr/bin/env python3
"""Classify every test function by what its assertions can actually constrain.

"A test that cannot fail is not a test." This finds the
candidates mechanically, across the whole suite, so the judging can be spent
on a short list instead of 4,956 functions.

Categories, worst first:
  TAUTOLOGY   an assertion that is true by construction (assert True, x == x)
  NO_CHECK    no assertion, no pytest.raises, no mock assert_* - can only fail
              if something throws
  SELF_FULFIL asserts only against a value the test itself assigned to a mock
  ISINSTANCE  asserts only the type of a result
  TYPE_CONST  asserts only on module-level constants, not on behaviour
  OK          everything else
"""
import ast
import pathlib
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tests")


def _names_assigned(fn):
    """Names the test body assigns, and mock attributes it configures."""
    assigned = set()
    mock_configured = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
                elif isinstance(t, ast.Attribute):
                    # mock.return_value = X  /  svc.load.return_value = X
                    if t.attr in ("return_value", "side_effect"):
                        mock_configured.add(ast.unparse(t.value))
    return assigned, mock_configured


def _is_tautology(test):
    if isinstance(test, ast.Constant) and test.value is True:
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1 \
            and isinstance(test.ops[0], (ast.Eq, ast.Is)):
        left, right = test.left, test.comparators[0]
        # `f(x) is f(x)` is NOT a tautology: it calls twice and checks that a
        # cache is a cache, or that a hash is deterministic. Only comparing two
        # inert expressions to each other is one.
        if any(isinstance(side, ast.Call) for side in (left, right)):
            return False
        try:
            if ast.unparse(left) == ast.unparse(right):
                return True
        except Exception:
            pass
    return False


def _is_isinstance(test):
    return (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
            and test.func.id == "isinstance")


def classify(fn, src_lines):
    asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
    has_raises = False
    has_mock_assert = False
    for n in ast.walk(fn):
        if isinstance(n, ast.withitem):
            try:
                if "raises" in ast.unparse(n.context_expr) or "warns" in ast.unparse(n.context_expr):
                    has_raises = True
            except Exception:
                pass
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr.startswith("assert_"):
            has_mock_assert = True
        # `pytest.fail(...)` and `self.fail(...)` ARE assertions - they are how
        # a test that collects findings reports them. So is an explicit
        # `raise AssertionError`. Counting them as "no check" is what made the
        # seven SAST security tests look unfailable when they are not.
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "fail":
            has_mock_assert = True
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) \
                and isinstance(n.exc.func, ast.Name) \
                and n.exc.func.id in ("AssertionError", "Failed"):
            has_mock_assert = True

    if asserts and all(_is_tautology(a.test) for a in asserts):
        return "TAUTOLOGY"

    if not asserts and not has_raises and not has_mock_assert:
        # A body that is only `pass` or a docstring is empty, not a smoke test.
        body = [b for b in fn.body if not (isinstance(b, ast.Expr)
                                           and isinstance(b.value, ast.Constant))]
        if not body or all(isinstance(b, ast.Pass) for b in body):
            return "EMPTY"
        return "NO_CHECK"

    if not asserts:
        return "OK"  # pytest.raises or mock assertions carry the check

    if has_mock_assert or has_raises:
        return "OK"

    if all(_is_isinstance(a.test) for a in asserts):
        return "ISINSTANCE"

    # Self-fulfilling: every assertion only compares against something the test
    # itself put into a mock.
    _assigned, configured = _names_assigned(fn)
    if configured:
        def only_against_configured(a):
            t = a.test
            if not (isinstance(t, ast.Compare) and len(t.ops) == 1
                    and isinstance(t.ops[0], ast.Eq)):
                return False
            try:
                right = ast.unparse(t.comparators[0])
            except Exception:
                return False
            return right in configured
        if asserts and all(only_against_configured(a) for a in asserts):
            return "SELF_FULFIL"

    return "OK"


def main():
    counts = Counter()
    flagged = defaultdict(list)
    files = sorted(ROOT.rglob("test_*.py"))
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError):
            counts["UNPARSED"] += 1
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            cat = classify(node, lines)
            counts[cat] += 1
            if cat != "OK":
                flagged[cat].append(f"{f}:{node.lineno} {node.name}")

    total = sum(v for k, v in counts.items() if k != "UNPARSED")
    print(f"{len(files)} test files, {total} test functions\n")
    for cat in ("TAUTOLOGY", "EMPTY", "NO_CHECK", "SELF_FULFIL", "ISINSTANCE", "OK"):
        if counts[cat]:
            print(f"  {cat:<12} {counts[cat]:>5}   {counts[cat]/total*100:5.1f} %")
    if counts["UNPARSED"]:
        print(f"  UNPARSED     {counts['UNPARSED']:>5} files")
    print()
    for cat in ("TAUTOLOGY", "EMPTY", "NO_CHECK", "SELF_FULFIL", "ISINSTANCE"):
        if not flagged[cat]:
            continue
        print(f"--- {cat} ({len(flagged[cat])}) " + "-" * 40)
        for entry in flagged[cat]:
            print("   ", entry)
        print()


if __name__ == "__main__":
    main()
