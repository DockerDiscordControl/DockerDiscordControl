#!/usr/bin/env python3
"""Build the review package for one section - and nothing else goes in.

Stage 4 of the quality programme: the reviewer gets the source of the
section, SPEC.md, the check plan of the section and the task - and NOTHING
else: no configuration, no credentials, no user data, no other code.

The package is built from an ALLOW-LIST, not a deny-list: only the pieces the
section lists in docs/quality/SECTIONS.txt, and only if they are .py files
under the application directories. Anything new is out until it is listed.
Each piece is written with its real line numbers, so a finding can name the
line in the repository.

Usage:
    python3 scripts/review/build_package.py 18 /path/to/package_dir
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_plan import PROJECT, read_sections, section_plan  # noqa: E402

ALLOWED_DIRS = ("cogs/", "services/", "app/", "utils/")
TASK = Path(__file__).resolve().parent / "REVIEW_TASK.md"


def build(number, target):
    pieces = read_sections()[number]
    if target.exists():
        shutil.rmtree(target)
    (target / "source").mkdir(parents=True)
    for path, start, end in pieces:
        if not (path.endswith(".py") and path.startswith(ALLOWED_DIRS)):
            raise SystemExit(f"not on the allow-list: {path}")
        lines = (PROJECT / path).read_text(encoding="utf-8").splitlines()
        body = "\n".join(f"{n:5d} | {lines[n - 1]}" for n in range(start, end + 1))
        name = path.replace("/", "~") + f".{start}-{end}.txt"  # "~": "__" collides with __init__
        (target / "source" / name).write_text(
            f"# {path}, lines {start}-{end} (numbers are the real line numbers)\n{body}\n",
            encoding="utf-8")
    shutil.copyfile(PROJECT / "SPEC.md", target / "SPEC.md")
    plan = section_plan(pieces)
    (target / "PLAN.txt").write_text("\n".join(plan) + "\n", encoding="utf-8")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT,
                            capture_output=True, text=True).stdout.strip()
    task = TASK.read_text(encoding="utf-8")
    (target / "TASK.md").write_text(
        task.replace("{SECTION}", f"{number:02d}").replace("{COMMIT}", commit)
            .replace("{NAMES}", str(len(plan))), encoding="utf-8")
    return len(pieces), len(plan)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("section", type=int)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    pieces, names = build(args.section, args.target)
    print(f"section {args.section:02d}: {pieces} pieces, {names} names -> {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
