# -*- coding: utf-8 -*-
"""No log line carries a commit hash typed into the source by hand.

THE OPERATOR (2026-09-25), after two log fixes: "please check the log once
more - does every message make sense now?" Most do. This one has been lying
since last November:

    [MODULE LOAD DEBUG] docker_control.py module is being loaded
                        - NEW CODE VERSION e214386

e214386a is a real commit - "DEBUG: Add comprehensive init logging to identify
crash point", 2025-11-13. It was true for exactly as long as that debugging
session lasted. The container that printed the line above was running 2501da2b,
some ten months and several hundred commits later, and announced e214386 at
INFO on every start. A second one sits at DEBUG in setup() naming 0f3d5cb, the
same day.

WHY THIS IS THE WORST LINE IN THE FILE, and not merely stale. A log line that
says which code is running is the line an operator trusts FIRST when something
behaves unexpectedly - it is where you go to check you are even looking at the
right build. This one answers that question confidently and wrongly. Three days
ago the container log named the wrong branch twice and cost an afternoon; this
week an INFO line about a regeneration that never happened cost a wrong
diagnosis. The pattern is the same and this is its purest form.

A HASH CANNOT BE TYPED IN, because the value is only known after the commit
that would contain it exists. So the honest options are to take it from the
build - DDC_VERSION is set by the Dockerfile and is already logged truthfully
at startup as "Version: 3.0.0" - or not to claim it at all. Both lines are
removed: the version is reported once, correctly, where an operator looks.

HOW THIS TEST CAN FAIL: somebody debugging pastes today's hash into a log
line, and it starts lying the moment they commit it.

COUNTER-CHECK (2026-09-25): red before - two lines, both hashes real commits
from 2025-11-13, neither of them the running code.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv", "docs"}

# Seven or more hex characters standing alone - what `git log --oneline` prints.
LOOKS_LIKE_A_HASH = re.compile(r"\b[0-9a-f]{7,40}\b")

# The words that turn a hex run into a CLAIM about which code is running.
CLAIMS_A_BUILD = re.compile(r"\b(version|build|commit|revision|rev|sha)\b", re.I)


def _log_messages():
    """(path, line, text) for every literal handed to a logger call."""
    for path in sorted(PROJECT.rglob("*.py")):
        if SKIP & set(path.relative_to(PROJECT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func)
            if not re.search(r"log(ger)?\.(debug|info|warning|error|critical|exception)$",
                             called):
                continue
            for argument in node.args:
                for piece in ast.walk(argument):
                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                        yield path.relative_to(PROJECT), node.lineno, piece.value


def _claims_a_build(text):
    """The hashes in `text`, but only where the line CLAIMS to name a build.

    THE FIRST VERSION OF THIS ASKED GIT, and the suite is run inside the
    production image, which has no git binary: `git cat-file` raised
    FileNotFoundError and two cases fell over. Good - it was the wrong
    question anyway. Whether a hash still resolves in this clone is an
    accident of history; a hash in a line that says "VERSION" is a claim
    about which code is running, and that is the decision worth flagging.
    It also catches the hash of a commit that has since been rebased away,
    which git would have quietly cleared.
    """
    if not CLAIMS_A_BUILD.search(text):
        return []
    return LOOKS_LIKE_A_HASH.findall(text)


def test_no_log_line_hardcodes_a_commit_hash():
    """THE FINDING: two lines naming a November 2025 debugging session."""
    offenders = []
    for path, line, text in _log_messages():
        for candidate in _claims_a_build(text):
            offenders.append(f"{path}:{line} names build {candidate}: {text[:70]}")

    assert offenders == [], (
        "a hash typed into the source is true until the next commit and a lie "
        f"afterwards - take the version from DDC_VERSION or drop the claim: {offenders}")


def test_the_scan_can_actually_find_one():
    """Counter-check, the one four earlier sabotages slipped past: a scanner
    that matches nothing passes the case above while proving nothing. Fed the
    two lines as they stood, it must flag both."""

    assert _claims_a_build(
        "[MODULE LOAD DEBUG] docker_control.py module is being loaded "
        "- NEW CODE VERSION e214386") == ["e214386"]
    assert _claims_a_build("setup() function called - NEW CODE VERSION 0f3d5cb") == ["0f3d5cb"]


def test_an_innocent_hex_run_is_not_flagged():
    """Counter-check the other way. A scanner must flag a DECISION, not an
    occurrence: a cache key, a colour or a container id must pass, or this
    cries wolf and teaches its reader to skip it."""
    for innocent in ("cache key deadbeef expired", "colour #ff00aa applied",
                     "container 05b406f5f790 started",
                     "Version: 3.0.0 (Optimized)"):

        assert _claims_a_build(innocent) == [], f"{innocent!r} would be reported"


def test_the_version_is_still_reported_somewhere():
    """The point is not an anonymous build. An operator must still be able to
    read which version is running - from the build, where it is true."""
    startup = (PROJECT / "app" / "web" / "security.py").read_text(encoding="utf-8")

    assert "DDC_VERSION" in startup, (
        "nothing reports the running version any more, which is the opposite mistake")
