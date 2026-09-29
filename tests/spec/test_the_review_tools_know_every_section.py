# -*- coding: utf-8 -*-
"""The review tools see every section SECTIONS.txt lists - also 19b and its kind.

THE FINDING (setting up the stage 4 review before v3.1.0, 2026-09-29).
scripts/review/check_plan.py read a section header as "## Section (\\d+)".
The sections cut out later carry a letter - 19b, 26b, 31b, 33b - and did not
match: their pieces were appended, silently, to the section before them.
CHECK_PLAN.txt said "49 sections" while SECTIONS.txt holds 53, a package for
"19b" could not be built, and the package for 19 held 19b as well. The
contract test on the split (test_stage4_sections.py) reads headers its own
way and never noticed.

THE CONTRACT: the tools' section list is the one in SECTIONS.txt - same
names, same pieces per section.

HOW THIS TEST CAN FAIL: a header form the tools do not read.

The expectation is read here with a separate, plain parse of the file, not
with the tools' own regex - otherwise the test would mirror the code.

COUNTER-CHECK (2026-09-29): red before the fix - 49 sections against 53,
19b/26b/31b/33b missing.
"""

import importlib.util
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


def _listed():
    """{section name: number of pieces}, read plainly from SECTIONS.txt."""
    listed, current = {}, None
    for line in (PROJECT / "docs" / "quality" / "SECTIONS.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("## Section "):
            current = line[len("## Section "):].split()[0]
            listed[current] = 0
        elif current and line.strip() and not line.startswith("#") and ".py:" in line:
            listed[current] += 1
    return listed


def _tools():
    spec = importlib.util.spec_from_file_location(
        "check_plan", PROJECT / "scripts" / "review" / "check_plan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_tools_see_every_section_with_its_own_pieces():
    listed = _listed()
    seen = {str(name): len(pieces) for name, pieces in _tools().read_sections().items()}

    assert {name.lstrip("0") for name in seen} == {name.lstrip("0") for name in listed}, (
        sorted({n.lstrip('0') for n in listed} - {n.lstrip('0') for n in seen}))
    for name, count in listed.items():
        match = next(v for k, v in seen.items() if k.lstrip("0") == name.lstrip("0"))
        assert match == count, f"section {name}: tools see {match} pieces, the file lists {count}"
