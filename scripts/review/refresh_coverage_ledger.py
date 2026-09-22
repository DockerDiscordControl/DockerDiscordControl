#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bring docs/quality/COVERAGE_BY_FILE.txt back in step with the tree.

The EVIDENCE column cannot be regenerated: it was recovered from the reviewer
packages, which live in a session scratchpad that is gone. This script only
refreshes what can drift - the line count of each file - and adds a file that
has appeared since with NONE, so a new module cannot slip in unnoticed.

A file that has vanished is reported rather than dropped, because losing a
file's review history silently is exactly the kind of bookkeeping rot this
ledger exists to stop.

    python3 scripts/review/refresh_coverage_ledger.py [--write]
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
LEDGER = PROJECT / "docs" / "quality" / "COVERAGE_BY_FILE.txt"
DIRECTORIES = ("cogs", "services", "app", "utils")


def main(write: bool) -> int:
    text = LEDGER.read_text(encoding="utf-8")
    header = [l for l in text.splitlines() if l.startswith("#") or not l.strip()]
    rows = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        path, _lines, *rest = line.split("\t")
        rows[path] = rest[0] if rest else "NONE"

    tree = {}
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            rel = str(path.relative_to(PROJECT))
            tree[rel] = len(path.read_text(encoding="utf-8", errors="replace").splitlines())

    added = sorted(set(tree) - set(rows))
    gone = sorted(set(rows) - set(tree))
    for path in added:
        rows[path] = "NONE"

    out = header + [f"{p}\t{tree[p]}\t{rows[p]}" for p in sorted(tree)]
    if write:
        LEDGER.write_text("\n".join(out) + "\n", encoding="utf-8")

    for path in added:
        print(f"added (no evidence): {path}")
    for path in gone:
        print(f"GONE from the tree, its review history is dropped: {path}")
    print(f"{len(tree)} files, {sum(1 for p in tree if rows[p] == 'NONE')} without evidence"
          f"{' - written' if write else ' - dry run, pass --write'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--write" in sys.argv))
