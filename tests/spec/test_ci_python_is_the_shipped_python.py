# -*- coding: utf-8 -*-
"""CI must test with the Python the image ships, not another one.

No ``@covers`` marker, but it serves Z10: "no image is shipped whose tests
have not run green" is only true if the green run used the shipped Python.

THE FINDING (2026-09-19): every workflow ran Python 3.10 (performance tests
3.10/3.11/3.12, Sonar analysed as 3.9-3.11), while the image runs 3.14
(alpine:3.24). A green CI run proved 3.10, not the image. It already made a
difference that day: seven spec tests failed on 3.10 only.

HOW IT IS CHECKED: the reference is the interpreter running this suite.
``scripts/ddc_test.sh`` runs it inside the shipped image, so locally this
compares the workflows with the real image Python. On CI the suite runs
under the workflow's own Python, so there the check holds by construction -
the check that matters is the one in the image.
"""

import re
import sys
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
VERSION = re.compile(r"\b3\.\d+\b")


def _python_versions():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # Whole comment lines set no version - they may name old ones to
            # explain the change (as tests.yml does). Only executed lines count.
            if "python" in line.lower() and not line.lstrip().startswith("#"):
                for version in VERSION.findall(line):
                    yield f"{path.name}:{number}", version


def test_the_scan_sees_the_workflows():
    """Guard against a blunt tool: no versions found would pass trivially."""
    assert len(list(_python_versions())) >= 10


def test_every_workflow_python_is_the_image_python():
    shipped = f"{sys.version_info.major}.{sys.version_info.minor}"
    wrong = [f"{where} {version}" for where, version in _python_versions() if version != shipped]
    assert not wrong, f"{len(wrong)} Python versions differ from the image's {shipped}: {wrong}"
