# -*- coding: utf-8 -*-
"""No log line above DEBUG is addressed to whoever is editing the code.

THE OPERATOR (2026-09-25): "does every message make sense now?" Two of them
were never meant for him at all. From his running container:

    INFO  MANUAL REGISTRATION IN setup_schedule_commands IS CURRENTLY
          DISABLED FOR TESTING.
    INFO  Ensuring other potential loops (if any residues from old structure)
          are cancelled.

The first shouts, in production, about a testing arrangement that has been
permanent for months - it describes how the code is wired, not what the bot is
doing, and there is nothing an operator can do with it either way. The second
is a note about a refactoring: "the old structure" is a thing that existed in
this repository, not in his server.

WHY IT BELONGS WITH THE OTHER LOG FINDINGS OF TODAY. A log has one reader, and
he has to be able to assume that every line is for him. Once some lines are
addressed to somebody else, every line has to be triaged before it can be read
- and that is the habit that let "attempting regeneration" go unquestioned for
as long as it did, and a hardcoded commit hash sit there for ten months. DEBUG
is where the wiring goes; it is one click away and always has been.

THE SCAN CRIED WOLF TWICE BEFORE IT WAS THIS NARROW. A first pass on
"temporary|deprecated|for now" reported 14 sites, 11 of them real
operator-facing features - "Temporary debug mode enabled for 30 minutes" is a
feature, not a leftover. Tightening it to phrases that ADMIT their audience
still caught "Clearing leftover individual server entry" (a leftover data
entry, which is a fact about his config) and "Please manually fix or remove
this file" (an instruction to him, which is the best kind of log line). Both
are excluded by name below, with the reason, so the next person does not
helpfully add them back.

HOW THIS TEST CAN FAIL: a log line at INFO or above that talks about the
source code's history, or about being disabled for testing.

COUNTER-CHECK (2026-09-25): red before - the two lines above.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv", "docs", "scripts"}

A_LOUD_LOG = re.compile(r"log(ger)?\.(info|warning|error|critical)$")

# Phrases that admit the line is addressed to whoever is editing the code.
# Deliberately NOT here, each having been tried and cried wolf:
#   temporary  - "Temporary debug mode enabled for 30 minutes" is a feature
#   deprecated - "Removed deprecated achieved_levels.json" is a migration result
#   for now    - appears inside a genuine error explaining config precedence
#   leftover   - "Clearing leftover individual server entry" is about his data
#   remove this- "Please manually fix or remove this file" is an instruction
#                to the operator, which is the best kind of log line there is
TALKING_TO_A_DEVELOPER = re.compile(
    r"\b(for testing|currently disabled|todo|fixme|hack|xxx|residues?|"
    r"old structure|work in progress|not implemented yet|disabled for now)\b", re.I)


def _loud_log_lines():
    """(path, line, level, text) for every literal logged at INFO or above."""
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
            level = A_LOUD_LOG.search(ast.unparse(node.func))
            if not level:
                continue
            for argument in node.args:
                for piece in ast.walk(argument):
                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                        yield path.relative_to(PROJECT), node.lineno, level.group(2), piece.value


def test_nothing_above_debug_talks_about_the_code_itself():
    """THE FINDING: a testing note and a refactoring note, both at INFO."""
    offenders = []
    for path, line, level, text in _loud_log_lines():
        if TALKING_TO_A_DEVELOPER.search(text):
            offenders.append(f"{path}:{line} [{level}] {text[:70]}")

    assert sorted(set(offenders)) == [], (
        "an operator has to be able to assume every line is for him - move the "
        f"wiring to DEBUG: {offenders}")


def test_the_scan_finds_the_lines_as_they_stood():
    """Counter-check, the one seven sabotages have slipped past: a scan that
    matches nothing passes the case above while proving nothing."""

    assert TALKING_TO_A_DEVELOPER.search(
        "MANUAL REGISTRATION IN setup_schedule_commands IS CURRENTLY DISABLED FOR TESTING.")
    assert TALKING_TO_A_DEVELOPER.search(
        "Ensuring other potential loops (if any residues from old structure) are cancelled.")
    assert TALKING_TO_A_DEVELOPER.search("TODO: rewrite this before the release")


def test_the_lines_that_cried_wolf_stay_unflagged():
    """Counter-check the other way, and the whole reason this pattern is so
    narrow. Each of these was reported by an earlier, wider version."""
    for innocent in ("===== TEMPORARY DEBUG MODE ENABLED for 30 minutes",
                     "Removed deprecated achieved_levels.json",
                     "Clearing leftover individual server entry 'Valheim'",
                     "has no valid Discord ID. Please manually fix or remove this file.",
                     "FIRST TIME SETUP: Setup mode activated with temporary credentials"):

        assert not TALKING_TO_A_DEVELOPER.search(innocent), f"{innocent!r} would be reported"


def test_the_wiring_is_still_said_at_debug():
    """The point is not deleting the information. Somebody debugging command
    registration still needs to know which path was taken."""
    source = (PROJECT / "app" / "bot" / "commands.py").read_text(encoding="utf-8")
    setup = next(node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.FunctionDef) and node.name == "setup_schedule_commands")

    assert "logger.debug" in ast.unparse(setup), (
        "the registration path is now completely unexplained, which is the "
        "opposite mistake")
