# -*- coding: utf-8 -*-
"""Nothing in the code says DDC runs as two processes, because it does not.

MEASURED IN THE RUNNING CONTAINER, 2026-09-25:

    PID 1   python3 run.py          the bot AND the web UI, 13 threads
    PID 57  allowlist_proxy.py      the Docker socket proxy, a different program
    supervisord                     not installed

Five docstrings said otherwise, in the present tense and with the mechanism
spelled out - "DDC runs as two processes (supervisord starts the bot and the
web UI)". That was true before v3 and has been false since.

THE LOCKS THEMSELVES ARE RIGHT AND STAY. cross_process_lock, ProcessSafeLock
and with_tasks_lock all guard a read-modify-write on a shared file, and that
is still needed: flock is held per open file description, so two threads
opening the same file DO block each other, and an operator editing
config/tasks.json by hand or through `docker exec` is a second writer that no
thread lock could ever see. Only the REASON given for them was wrong.

WHY A WRONG COMMENT IS WORTH A COMMIT. Twice today a stale description of how
DDC works cost real time: ToggleButton read as live code and I told the
operator something false about his own panel, and a supervisord log from last
November was served as the present. A comment is where somebody goes to find
out how the program works, and one that is wrong there is worse than none -
it is confidently wrong, and it is believed.

HOW THIS TEST CAN FAIL: a comment or docstring stating that DDC runs as two
processes, or that supervisord starts anything.

COUNTER-CHECK (2026-09-25): red before - five sites in four files.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
NOT_APP_CODE = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv", "docs", "scripts"}

# A CLAIM, not a mention. The wording a correction uses - "used to say",
# "before v3", "is ONE process" - has to stay sayable, or the next person
# cannot explain why the line changed. So this matches the assertion itself:
# DDC, or its two halves, running as two processes, in the present tense.
A_CLAIM = re.compile(
    r"(DDC runs as two processes"
    r"|are two processes"
    r"|is written by two processes"
    r"|bot and the web (panel|UI) are two"
    r"|supervisord starts)", re.I)


def _lines_of_prose():
    """Every comment and docstring line in the application code.

    Read as text on purpose: a docstring IS a string, and a `#` comment is
    not in the syntax tree at all, so this is the one scan of the day that
    genuinely wants the characters.
    """
    for path in sorted(PROJECT.rglob("*.py")):
        if NOT_APP_CODE & set(path.relative_to(PROJECT).parts):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            yield path.relative_to(PROJECT), number, line


def test_nothing_says_the_bot_and_the_panel_are_separate_processes():
    """THE FINDING: five present-tense claims about an architecture that
    changed in v3."""
    claims = [f"{path}:{number}: {line.strip()[:70]}"
              for path, number, line in _lines_of_prose() if A_CLAIM.search(line)]

    assert sorted(claims) == [], (
        "the bot and the web UI are ONE process with threads - measured, PID 1 "
        f"is python3 run.py: {sorted(claims)}")


def test_the_pattern_would_catch_the_lines_that_were_there():
    """Counter-check, the one ten sabotages have walked past: a pattern
    matching nothing passes the case above while proving nothing."""
    for gone in ("DDC runs as two processes (supervisord starts the bot and the web UI)",
                 "The bot and the web UI are two processes (supervisord), where a thread",
                 "because the bot and the web panel are two processes."):

        assert A_CLAIM.search(gone), gone


def test_a_correction_may_still_explain_itself():
    """The other way, and the mistake five scans of mine made today: an
    explanation of what the line used to say must stay sayable, or nobody can
    record why it changed."""
    for allowed in ("# This used to say DDC ran as two processes under supervisord.",
                    "# Before v3 the bot and the web UI were separate; they are one now.",
                    "# The lock still matters: a second writer may be an operator's editor."):

        assert not A_CLAIM.search(allowed), allowed


def test_the_locks_are_all_still_there():
    """The opposite mistake. Correcting the reason must not remove the guard:
    flock is per open file description, so two THREADS opening the same file
    block each other, and an operator editing the file by hand is a writer no
    thread lock can see."""
    guards = {"cross_process_lock": "utils/atomic_io.py",
              "with_tasks_lock": "services/scheduling/runtime.py",
              "ProcessSafeLock": "services/mech/progress/runtime.py"}
    for name, path in guards.items():
        source = (PROJECT / path).read_text(encoding="utf-8")

        assert f"def {name}" in source or f"class {name}" in source, f"{name} is gone from {path}"
