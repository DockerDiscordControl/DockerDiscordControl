# -*- coding: utf-8 -*-
"""A case that names another case names one that exists.

WHY THESE POINTERS ARE WORTH ANYTHING. The files in tests/spec explain
themselves to whoever reads them next, and they lean on each other to do it:
"the rule this replaces is in …", "the proof is in …". Following one is how
somebody finds out why a line is the way it is.

THE FINDING (2026-09-25). Three of them pointed at
``tests/spec/test_no_control_flips_an_expand_state.py``, which had been
deleted hours earlier - its subject, a container's expand state, was removed
in full, so the file had no subject left. Deleting it was right; leaving three
signposts to it was not. Whoever followed one would conclude the proof had
never existed.

IT IS THE SAME DEFECT AS THE REST OF THE DAY, and it was mine: a statement
the repository makes that is not true. A dead pointer costs the reader more
than no pointer, because they spend the search before they give up.

WHAT IS CHECKED: only references to other spec files, written as a path. Those
are meant to be followed. A source file named with a line number
(``cogs/control_ui.py:2092``) is a note about where something stood at the
time and goes stale by design, which is a different question and not this
one's to answer.

HOW THIS TEST CAN FAIL: a case naming a spec file that is not there - because
it was renamed, deleted, or typed wrong.

COUNTER-CHECK (2026-09-25): red before, naming all three.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SPEC = PROJECT / "tests" / "spec"

A_POINTER = re.compile(r"tests/spec/(test_[a-z0-9_]+\.py)")


# THIS FILE IS ITS OWN EXCEPTION, and the reason is the finding itself: to
# describe what went wrong it has to NAME the deleted file, and to prove the
# scanner bites it has to invent one. Both are dead names on purpose. It is
# the sixth time today one of my own explanations tripped one of my own
# scans, so the exception is written here rather than worked around.
DESCRIBES_THE_FINDING = "test_a_pointer_to_another_case_leads_somewhere.py"


def _dangling():
    found = []
    for path in sorted(SPEC.glob("test_*.py")):
        if path.name == DESCRIBES_THE_FINDING:
            continue
        text = path.read_text(encoding="utf-8")
        for named in sorted(set(A_POINTER.findall(text))):
            if not (SPEC / named).is_file():
                found.append(f"{path.name} -> {named}")
    return found


def test_no_case_points_at_one_that_is_not_there():
    """THE FINDING: three signposts to a file deleted the same day."""
    assert _dangling() == [], (
        "these name a spec file that does not exist, so nobody can follow "
        f"them: {_dangling()}")


def test_the_scan_finds_the_pointers_that_do_lead_somewhere():
    """The counter-check eleven sabotages have walked past: a pattern that
    matches nothing passes the case above while proving nothing."""
    live = set()
    for path in sorted(SPEC.glob("test_*.py")):
        for named in A_POINTER.findall(path.read_text(encoding="utf-8")):
            if (SPEC / named).is_file():
                live.add(named)

    # 19 distinct spec files are pointed at today; the floor is set just
    # below that so removing one case does not turn this red for the wrong
    # reason, while a pattern that stops matching still does.
    assert len(live) >= 15, f"only {len(live)} working pointers found - pattern blind?"


def test_a_missing_file_is_seen_whatever_it_is_called():
    """The scanner on text of its own, so the case above cannot pass merely
    because the repository happens to be tidy."""
    invented = A_POINTER.findall(
        "the rule moved to tests/spec/test_something_that_never_existed.py\n")

    assert invented == ["test_something_that_never_existed.py"], invented
    assert not (SPEC / invented[0]).is_file()


def test_a_source_file_with_a_line_number_is_not_a_pointer():
    """The opposite mistake. Notes like cogs/control_ui.py:2092 record where
    something stood, and they go stale by design; pulling them into this rule
    would make the file red for a reason its name does not describe."""
    assert A_POINTER.findall("see cogs/control_ui.py:2092 and app/web/tls.py") == []
