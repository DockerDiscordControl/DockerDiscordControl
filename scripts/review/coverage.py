#!/usr/bin/env python3
"""Hold a review report against the check plan of its section.

Stage 4 of the quality programme: "72 of 74 functions checked" is worthless
as long as nobody knows WHICH two are missing. This prints, for one report:
how many plan names got a verdict, which got none, which verdicts name
something that is not in the plan (invented or misspelt), which names were
judged twice, and which findings lack a required field or point outside the
section.

The report is the REPORT.json a reviewer writes into the package (see
REVIEW_TASK.md for its shape). Exit code 1 if anything is missing or
invented, so the gap cannot be read past.

Usage:
    python3 scripts/review/coverage.py PACKAGE_DIR
"""

import json
import sys
from collections import Counter
from pathlib import Path

REQUIRED = ("id", "file", "line", "trigger", "suggestion", "severity", "certainty")
VERDICTS = ("checked", "finding", "not_checked")


def main(package):
    plan = [line for line in (package / "PLAN.txt").read_text(encoding="utf-8").splitlines() if line]
    report = json.loads((package / "REPORT.json").read_text(encoding="utf-8"))
    verdicts = report.get("verdicts", [])
    findings = report.get("findings", [])
    named = Counter(v.get("name") for v in verdicts)

    missing = [n for n in plan if n not in named]
    invented = sorted(n for n in named if n not in plan)
    twice = sorted(n for n, k in named.items() if k > 1)
    bad_kind = [v for v in verdicts if v.get("verdict") not in VERDICTS]
    unexplained = [v["name"] for v in verdicts
                   if v.get("verdict") == "not_checked" and not v.get("reason")]
    ids = {f.get("id") for f in findings}
    dangling = [v["name"] for v in verdicts
                if v.get("verdict") == "finding" and v.get("finding") not in ids]
    incomplete = [f.get("id", "?") for f in findings if any(not f.get(k) and f.get(k) != 0 for k in REQUIRED)]
    pieces = {}
    for src in (package / "source").glob("*.txt"):
        stem, span = src.name[:-4].rsplit(".", 1)
        start, end = (int(x) for x in span.split("-"))
        pieces.setdefault(stem.replace("~", "/"), []).append((start, end))
    outside = [f.get("id") for f in findings
               if not any(s <= int(f.get("line", 0)) <= e for s, e in pieces.get(f.get("file"), []))]

    judged = len(plan) - len(missing)
    kinds = Counter(v.get("verdict") for v in verdicts)
    print(f"plan names: {len(plan)}  judged: {judged}  "
          f"(checked {kinds['checked']}, finding {kinds['finding']}, not_checked {kinds['not_checked']})")
    print(f"findings: {len(findings)}  "
          f"(unsure: {sum(1 for f in findings if f.get('certainty') == 'unsure')})")
    problems = {"missing": missing, "invented": invented, "judged twice": twice,
                "unknown verdict": [v.get("name") for v in bad_kind],
                "not_checked without reason": unexplained,
                "verdict points to no finding": dangling,
                "finding lacks a field": incomplete,
                "finding outside the section": outside}
    for label, items in problems.items():
        if items:
            print(f"{label} ({len(items)}): {items}")
    return 1 if missing or invented else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
