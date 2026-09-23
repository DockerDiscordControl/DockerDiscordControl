# -*- coding: utf-8 -*-
"""There is one entrypoint, and it is the one the image runs.

THE FINDING (independent review, carried open until 2026-09-23): the repo still
held `docker/entrypoint.sh` from before v3.0, next to the `scripts/entrypoint.sh`
the Dockerfile actually copies. The old one does the one thing v3.0's whole
boundary exists to prevent: it adds DDC's own user to the Docker socket's group,
so DDC talks to the daemon directly instead of through the allowlist proxy.

Nothing runs it. That is the danger - it reads like the entrypoint, it is
named like the entrypoint, and a `docker-compose.yml` comment cited it as the
source of its capability list. Wiring it back in would undo the boundary
without changing a line of Python, and `check_image_boundary.sh` is run against
a built image, so nothing in the repo would have objected first.

WHAT THIS TEST PINS: exactly one entrypoint script, at the path the Dockerfile
copies. A second one is red whatever it contains, because the danger is the
name, not the content.

COUNTER-CHECK (2026-09-23): red before - it named docker/entrypoint.sh. The
second test proves the scan can see a file at all, so a passing first test is
not an empty search.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


def _entrypoints():
    """Every entrypoint script in the repo, as repo-relative paths."""
    return sorted(
        path.relative_to(PROJECT).as_posix()
        for path in PROJECT.rglob("entrypoint*.sh")
        if ".git" not in path.parts and "node_modules" not in path.parts
    )


def _entrypoint_the_image_runs():
    """The path the Dockerfile copies to /app/entrypoint.sh."""
    dockerfile = (PROJECT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^COPY\s+(\S+)\s+/app/entrypoint\.sh\s*$", dockerfile, re.MULTILINE)
    assert match, "the Dockerfile no longer copies an entrypoint to /app/entrypoint.sh"
    return match.group(1)


def test_the_repo_holds_only_the_entrypoint_the_image_runs():
    found = _entrypoints()
    used = _entrypoint_the_image_runs()

    assert found == [used], (
        f"the image runs {used}, but the repo also holds {[p for p in found if p != used]} - "
        "a second file named entrypoint reads like the real one and can be wired back in")


def test_the_scan_sees_the_entrypoint_at_all():
    """Counter-check: a search that finds nothing would pass the test above."""
    assert _entrypoints(), "the scan found no entrypoint script at all"
    assert (PROJECT / _entrypoint_the_image_runs()).exists()
