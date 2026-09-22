#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mechanical inventory of the test suite (stage 0).

Reads EVERY test function via AST and classifies it. No model, no sampling:
what is written here is countable and repeatable.

Categories:
  no_verification   - no assert, no pytest.raises, no mock.assert_*
  only_trivial      - there are asserts, but ALL of them say nothing
                      (is not None / isinstance / hasattr / assert True / x == x)
  broad_raises      - pytest.raises(Exception) or similar: catches everything
  mock_tautology    - checks a literal the test itself set as return_value
  only_mock_calls   - verifies exclusively through mock.assert_called*(...)
Additionally: module-wide pollution (sys.modules, os.environ, importlib.reload)
at module level, i.e. on import - the source of order dependence.
"""
from __future__ import annotations

import ast
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
TESTS = ROOT / "tests"

TRIVIAL_FUNCS = {"isinstance", "hasattr", "callable", "issubclass", "len", "bool", "id", "type"}


def dump(node) -> str:
    try:
        return ast.dump(node)
    except Exception:
        return repr(node)


def src(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<?>"


def classify_assert(node: ast.Assert) -> str | None:
    """Returns the reason an assert is trivial, or None if the assert says something."""
    t = node.test

    # assert True / assert 1 / assert "x"
    if isinstance(t, ast.Constant):
        return "konstante" if t.value else None

    # assert isinstance(...) / hasattr(...) / callable(...)
    if isinstance(t, ast.Call) and isinstance(t.func, ast.Name) and t.func.id in TRIVIAL_FUNCS:
        return f"nur {t.func.id}()"

    if isinstance(t, ast.Compare) and len(t.ops) == 1:
        op, right = t.ops[0], t.comparators[0]
        left = t.left
        # assert x is not None  /  assert x is None
        if isinstance(op, (ast.IsNot, ast.Is)) and isinstance(right, ast.Constant) and right.value is None:
            return "is (not) None"
        # assert x == x
        if isinstance(op, (ast.Eq, ast.Is)) and dump(left) == dump(right):
            return "x == x"
        # assert len(x) >= 0  /  > -1
        if (isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id == "len"
                and isinstance(right, ast.Constant) and isinstance(right.value, int)):
            if (isinstance(op, ast.GtE) and right.value <= 0) or (isinstance(op, ast.Gt) and right.value < 0):
                return "len(x) >= 0"
        # assert isinstance-Aufruf in Vergleich
        if isinstance(left, ast.Call) and isinstance(left.func, ast.Name) and left.func.id in TRIVIAL_FUNCS:
            if isinstance(right, ast.Constant) and right.value in (True, False):
                return f"nur {left.func.id}()"
    return None


def is_broad_raises(call: ast.Call) -> bool:
    """pytest.raises(Exception) or a tuple containing Exception/BaseException."""
    if not call.args:
        return False
    targets = call.args[0].elts if isinstance(call.args[0], ast.Tuple) else [call.args[0]]
    return any(isinstance(a, ast.Name) and a.id in ("Exception", "BaseException") for a in targets)


class FuncAnalysis:
    def __init__(self, fn, path, cls):
        self.fn, self.path, self.cls = fn, path, cls
        self.asserts: list[ast.Assert] = []
        self.trivial_reasons: list[str] = []
        self.raises: list[ast.Call] = []
        self.broad_raises: list[ast.Call] = []
        self.mock_asserts = 0
        self.unittest_asserts = 0
        self.explicit_fails = 0   # pytest.fail(...) / self.fail(...) / raise AssertionError
        self.helper_asserts = 0   # call to a helper named assert_* / verify_*
        self.return_value_literals: dict[str, ast.AST] = {}
        self.tautologies: list[tuple[int, str]] = []
        # Lines of the asserts that say nothing (trivial OR tautology).
        # A test is only hollow when ALL its asserts are here - a single
        # hollow assert next to a real check is harmless.
        self.hollow_lines: set[int] = set()
        self.skipped = False

    @property
    def name(self):
        return f"{self.cls}::{self.fn.name}" if self.cls else self.fn.name

    @property
    def loc(self):
        return f"{self.path}:{self.fn.lineno}"

    def verifications(self):
        return (len(self.asserts) + len(self.raises) + self.mock_asserts
                + self.unittest_asserts + self.explicit_fails + self.helper_asserts)

    def category(self):
        if self.skipped:
            return "skipped"
        if self.verifications() == 0:
            return "no_verification"
        # Other ways of checking than a plain assert - if there are any, the test is not hollow.
        other = (self.mock_asserts + self.unittest_asserts + self.explicit_fails
                 + self.helper_asserts + len(self.raises))
        if self.asserts and len(self.hollow_lines) == len(self.asserts) and other == 0:
            return "mock_tautology" if self.tautologies else "only_trivial"
        if self.broad_raises and not self.asserts and self.mock_asserts == 0:
            return "broad_raises"
        if not self.asserts and self.mock_asserts > 0 and self.explicit_fails == 0:
            return "only_mock_calls"
        return "ok"


def analyse_function(fn, path, cls) -> FuncAnalysis:
    a = FuncAnalysis(fn, path, cls)

    for dec in fn.decorator_list:
        d = src(dec)
        if "skip" in d or "xfail" in d:
            a.skipped = True

    # First collect the return_value literals the test set itself.
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr in ("return_value", "side_effect"):
                    a.return_value_literals[repr(node.value.value)] = node.value

    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            a.asserts.append(node)
            reason = classify_assert(node)
            if reason:
                a.trivial_reasons.append(reason)
                a.hollow_lines.add(node.lineno)
            # Tautology: compares against a literal the test set itself
            t = node.test
            if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq):
                for side in (t.left, t.comparators[0]):
                    if isinstance(side, ast.Constant) and repr(side.value) in a.return_value_literals:
                        if not isinstance(side.value, (bool, type(None))) and side.value not in (0, 1, "", []):
                            a.tautologies.append((node.lineno, src(node)))
                            a.hollow_lines.add(node.lineno)
                        break
        elif isinstance(node, ast.Raise):
            # raise AssertionError(...) is a check just like an assert.
            exc = node.exc
            nm = exc.func if isinstance(exc, ast.Call) else exc
            if isinstance(nm, ast.Name) and nm.id in ("AssertionError", "Failed"):
                a.explicit_fails += 1
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                if f.attr == "raises" and isinstance(f.value, ast.Name) and f.value.id == "pytest":
                    a.raises.append(node)
                    if is_broad_raises(node):
                        a.broad_raises.append(node)
                # pytest.fail(...) / self.fail(...) - checks without being called assert.
                elif f.attr in ("fail", "assertRaises", "assertRaisesRegex"):
                    a.explicit_fails += 1
                elif f.attr.startswith("assert_"):
                    a.mock_asserts += 1
                elif f.attr.startswith("assert") and f.attr != "assert_":
                    a.unittest_asserts += 1
            elif isinstance(f, ast.Name):
                # Helper function whose name says that it checks.
                if f.id.lstrip("_").startswith(("assert", "verify", "expect", "check_")):
                    a.helper_asserts += 1
                elif f.id == "fail":
                    a.explicit_fails += 1
    return a


def module_pollution(tree, path) -> list[str]:
    """Module level only: what happens process-wide on IMPORT of the file."""
    found = []
    for node in tree.body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for tgt in sub.targets:
                    s = src(tgt)
                    if s.startswith("sys.modules["):
                        found.append(f"{path}:{sub.lineno}: setzt {s}")
                    elif s.startswith("os.environ["):
                        found.append(f"{path}:{sub.lineno}: setzt {s}")
            elif isinstance(sub, ast.Delete):
                for tgt in sub.targets:
                    s = src(tgt)
                    if s.startswith("sys.modules["):
                        found.append(f"{path}:{sub.lineno}: loescht {s}")
            elif isinstance(sub, ast.Call):
                s = src(sub.func)
                if s in ("importlib.reload", "reload"):
                    found.append(f"{path}:{sub.lineno}: {src(sub)}")
                elif s in ("os.environ.setdefault", "os.environ.pop", "os.environ.update"):
                    found.append(f"{path}:{sub.lineno}: {src(sub)}")
    return found


def walk_module(tree, path):
    """Find test functions, including those in test classes."""
    out = []

    def visit(body, cls):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    out.append(analyse_function(node, path, cls))
            elif isinstance(node, ast.ClassDef):
                visit(node.body, node.name)

    visit(tree.body, None)
    return out


def main():
    results, pollution, parse_errors = [], [], []
    files = sorted(TESTS.rglob("test_*.py")) + sorted(TESTS.rglob("*_test.py"))
    for f in files:
        rel = f.relative_to(ROOT)
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"), filename=str(f))
        except SyntaxError as e:
            parse_errors.append(f"{rel}: {e}")
            continue
        results.extend(walk_module(tree, str(rel)))
        pollution.extend(module_pollution(tree, str(rel)))

    cats = Counter(r.category() for r in results)
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r.category()].append(r)

    print(f"Dateien: {len(files)}   Testfunktionen: {len(results)}")
    if parse_errors:
        print(f"NICHT GEPARST: {len(parse_errors)}")
        for e in parse_errors:
            print("   ", e)
    print()
    print("=== Einstufung ===")
    for cat, n in cats.most_common():
        pct = 100 * n / len(results) if results else 0
        print(f"{cat:18s} {n:5d}  ({pct:4.1f}%)")

    print()
    for cat in ("no_verification", "only_trivial", "mock_tautology", "broad_raises", "skipped"):
        items = by_cat.get(cat, [])
        if not items:
            continue
        print(f"=== {cat}: {len(items)} ===")
        per_file = Counter(r.path for r in items)
        for path, n in per_file.most_common(15):
            print(f"   {n:4d}  {path}")
        print("   Beispiele:")
        for r in items[:12]:
            extra = ""
            if cat == "only_trivial":
                extra = " | " + ", ".join(sorted(set(r.trivial_reasons)))
            if cat == "mock_tautology":
                extra = " | " + r.tautologies[0][1][:90]
            print(f"     {r.loc}  {r.name}{extra}")
        print()

    print(f"=== Modulweite Verschmutzung beim Import: {len(pollution)} Stellen ===")
    per_file = Counter(p.split(":")[0] for p in pollution)
    for path, n in per_file.most_common(20):
        print(f"   {n:4d}  {path}")

    out = {
        "total_files": len(files),
        "total_tests": len(results),
        "categories": dict(cats),
        "findings": {
            cat: [{"loc": r.loc, "name": r.name,
                   "reasons": sorted(set(r.trivial_reasons)),
                   "tautology": r.tautologies[0][1] if r.tautologies else None}
                  for r in by_cat.get(cat, [])]
            for cat in ("no_verification", "only_trivial", "mock_tautology", "broad_raises", "skipped")
        },
        "module_pollution": pollution,
        "parse_errors": parse_errors,
    }
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("test_audit.json")
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nVolle Liste: {dest}")


if __name__ == "__main__":
    main()
