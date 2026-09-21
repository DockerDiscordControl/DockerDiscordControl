#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The two mechanical scans from the stage-4 review, made repeatable.

Both came out of section 26 (`scheduler.py`), where the same sentence turned
up three times by hand: *a failure that looks like an empty result*. One
sentence found three times by hand is a sentence worth looking for by machine.
See `docs/quality/reviews/SCANS_2026-09-21.md` for what they found.

    scan 1  --falsy    every `except` block that answers with None/False/[]/{}/''
    scan 2  --ddc      every narrow `except (...)` in front of a call that can
                       raise a DDCBaseException

READ THIS BEFORE BELIEVING A HIT.

Scan 2 matches **by name**. It builds the set of function and method names in
the repo that raise a DDC exception, then flags calls to those names sitting
under a handler that cannot catch one. It cannot tell two methods apart that
share a name - and they do: `spam_service.save_config` returns a ServiceResult
and raises nothing, while `config_service.save_config` raises ConfigSaveError.
That pair produced a false positive in the first run of this scan.

So: **a hit is a question, not a finding.** Read it back to the definition
that is actually called before it counts as anything. And a narrow handler is
not a defect when the right handler is one frame up - which is how
`configuration_save_service.py` came out of the first run clean.

Neither scan finds behaviour. They find shapes.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SKIP_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv", "build", "dist"}

FALSY = {None, False, "", 0}


def _source_files(paths: list[str]) -> list[Path]:
    if paths:
        return [REPO / p for p in paths]
    out = []
    for path in REPO.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if "tests" in path.parts or "scripts" in path.parts:
            continue
        out.append(path)
    return sorted(out)


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"  ! could not parse {path.relative_to(REPO)}: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# The set of names that raise a DDC exception, read out of the code itself.
# --------------------------------------------------------------------------- #

def _ddc_exception_names() -> set[str]:
    """Every class in services/exceptions.py that descends from DDCBaseException."""
    tree = _parse(REPO / "services" / "exceptions.py")
    if tree is None:
        return set()
    by_name = {node.name: [b.id for b in node.bases if isinstance(b, ast.Name)]
               for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    found = {"DDCBaseException"}
    changed = True
    while changed:                      # resolve the hierarchy, not just direct bases
        changed = False
        for name, bases in by_name.items():
            if name not in found and any(b in found for b in bases):
                found.add(name)
                changed = True
    return found


def _raisers(files: list[Path], ddc: set[str], depth: int = 3) -> dict[str, int]:
    """Function names that raise a DDC exception, and how far away they raise it.

    Depth 0 is a function with the ``raise`` in its own body. Depth 1 calls one
    of those and does not catch it, and so on.

    **The propagation is the point.** A scanner that only found depth 0 would
    have missed E12, the finding this whole script came out of: the handler
    there sits over ``add_system_donation``, which raises nothing itself - it
    calls ``_heal_if_lagging`` under the lock, and THAT raises. One level of
    distance was enough to hide it from a reader, and it would have been enough
    to hide it from a direct-only scan. `--selftest` pins exactly that.

    Propagation is by NAME and it is deliberately generous: a call inside a try
    whose handler catches everything does not propagate, and nothing else is
    subtracted. Depth is capped because without a cap most of the repo ends up
    marked, and a scan that flags everything says nothing.
    """
    direct: set[str] = set()
    calls: dict[str, set[str]] = {}

    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Calls that a local handler already absorbs cannot propagate out.
            swallowed = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Try) and any(
                        _handler_catches_everything(h, ddc) for h in sub.handlers):
                    for stmt in sub.body:
                        swallowed |= _called_names(stmt)
            calls.setdefault(node.name, set()).update(_called_names(node) - swallowed)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Raise) and sub.exc is not None:
                    call = sub.exc.func if isinstance(sub.exc, ast.Call) else sub.exc
                    raised = getattr(call, "id", None) or getattr(call, "attr", None)
                    if raised in ddc:
                        direct.add(node.name)
                        break

    known = {name: 0 for name in direct}
    for level in range(1, depth + 1):
        for name, called in calls.items():
            if name in known:
                continue
            if called & known.keys():
                known[name] = level
    return known


def _handler_catches_everything(handler: ast.ExceptHandler, ddc: set[str]) -> bool:
    if handler.type is None:
        return True
    parts = (handler.type.elts if isinstance(handler.type, ast.Tuple)
             else [handler.type])
    for part in parts:
        name = getattr(part, "id", None) or getattr(part, "attr", None)
        if name in {"Exception", "BaseException"} or name in ddc:
            return True
    return False


def _called_names(node: ast.AST) -> set[str]:
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            name = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
            if name:
                out.add(name)
    return out


def _returns_falsy(handler: ast.ExceptHandler) -> str | None:
    for sub in ast.walk(handler):
        if isinstance(sub, ast.Return) and sub.value is not None:
            value = sub.value
            if isinstance(value, ast.Constant) and value.value in FALSY:
                return repr(value.value)
            if isinstance(value, (ast.List, ast.Dict)) and not getattr(value, "elts", getattr(value, "keys", [1])):
                return "[]" if isinstance(value, ast.List) else "{}"
        if isinstance(sub, ast.Return) and sub.value is None:
            return "None"
    return None


# --------------------------------------------------------------------------- #
# A scan that cannot find the finding it was built from is not a scan.
# --------------------------------------------------------------------------- #

E12_COMMIT = "fc3ca28"     # "A damaged mech no longer silences the donation appeal"
E12_FILE = "services/scheduling/donation_message_service.py"


def selftest() -> int:
    """Re-run the scan against the code as it stood BEFORE E12 was repaired.

    The point is not that the script runs. The point is that it still answers
    the question it was written to answer - and that it would have gone quiet
    if the propagation in `_raisers` were removed, because the handler in that
    file sits over `add_system_donation`, which raises nothing itself.
    """
    import subprocess
    import tempfile

    try:
        before = subprocess.run(
            ["git", "show", f"{E12_COMMIT}^:{E12_FILE}"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"selftest SKIPPED: cannot read the pre-E12 file ({e})")
        return 0

    ddc = _ddc_exception_names()
    raisers = _raisers(_source_files([]), ddc, depth=3)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "donation_message_service.py"
        path.write_text(before, encoding="utf-8")
        tree = _parse(path)
        hits = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            called = set()
            for stmt in node.body:
                called |= _called_names(stmt)
            for handler in node.handlers:
                if _handler_catches_everything(handler, ddc):
                    continue
                if called & raisers.keys():
                    hits.append((handler.lineno, sorted(called & raisers.keys())))

    if not hits:
        print("selftest FAILED: the pre-E12 file scans clean. The scan no longer "
              "finds the finding it was built from - most likely the propagation "
              "in _raisers is gone, since add_system_donation raises nothing itself.")
        return 1

    print(f"selftest ok: {len(hits)} hit(s) in the pre-E12 file")
    for lineno, names in hits:
        print(f"  {E12_FILE}:{lineno}  over {', '.join(names)}")
    if not any("add_system_donation" in names for _l, names in hits):
        print("selftest FAILED: hits found, but not the one over add_system_donation "
              "- that is the E12 handler, and it is the only one that matters here.")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--falsy", action="store_true", help="scan 1")
    ap.add_argument("--ddc", action="store_true", help="scan 2")
    ap.add_argument("--depth", type=int, default=3,
                    help="how far a raise may travel through calls (default 3)")
    ap.add_argument("--selftest", action="store_true",
                    help="check the scan still finds E12, the finding it came from")
    ap.add_argument("files", nargs="*", help="repo-relative paths (default: all source)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not (args.falsy or args.ddc):
        args.falsy = args.ddc = True

    targets = _source_files(args.files)
    ddc = _ddc_exception_names()
    # The raiser set is built from the WHOLE repo, never just the targets:
    # the call that raises usually lives somewhere else entirely.
    raisers = _raisers(_source_files([]), ddc, depth=args.depth)
    direct = sum(1 for d in raisers.values() if d == 0)
    print(f"# {len(ddc)} DDC exception classes, {direct} function names that raise "
          f"one directly, {len(raisers) - direct} that pass one on "
          f"(depth <= {args.depth}), {len(targets)} files scanned\n")

    falsy_hits = ddc_hits = 0
    for path in targets:
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(REPO)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            called = set()
            for stmt in node.body:
                called |= _called_names(stmt)
            for handler in node.handlers:
                catches_all = _handler_catches_everything(handler, ddc)
                if args.falsy:
                    answer = _returns_falsy(handler)
                    if answer is not None:
                        falsy_hits += 1
                        print(f"FALSY  {rel}:{handler.lineno}  answers {answer}")
                if args.ddc and not catches_all:
                    risky = sorted(called & raisers.keys(),
                                   key=lambda n: (raisers[n], n))
                    if risky:
                        ddc_hits += 1
                        shown = ", ".join(f"{n} (+{raisers[n]})" for n in risky)
                        print(f"DDC    {rel}:{handler.lineno}  "
                              f"narrow handler over: {shown}")

    print(f"\n# {falsy_hits} falsy hits, {ddc_hits} DDC hits. "
          f"Every one is a question, not a finding - read the docstring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
