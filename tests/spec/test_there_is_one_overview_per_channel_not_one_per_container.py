# -*- coding: utf-8 -*-
"""DDC keeps one overview message per channel, and no code for the old design.

THE OPERATOR (2026-09-25), correcting me: "there is no expand/collapse here -
that was a long time ago." I had just told him control_ui.py:1030 was "the
expand/collapse on the public panel". It is not: his channels each carry a
single overview message, and the code for the older design - one message per
container, each with its own buttons - is still in the tree and still reads as
if it ran.

THE DESIGN SAYS SO ITSELF. The periodic edit loop handles exactly two tracked
names and throws the rest away:

    if display_name == "overview":         ...
    if display_name == "admin_overview":   ...
    if display_name not in ["overview", "admin_overview"]:
        logger.warning("Removing phantom individual server entry ...")
        del server_messages_in_channel[display_name]

A per-container message could not survive one pass of that loop.

WHAT WAS PROVABLY UNREACHABLE, by callers rather than by opinion:

    send_server_status                     0 callers
    _edit_single_message_wrapper (x2)      0 callers
    _edit_single_message                   only those two wrappers
    tracked_status_messages                read in four places behind
                                           hasattr(), ASSIGNED IN NONE

269 lines in status_handlers.py and 50 in message_updates.py, plus two loops
that could never run because the attribute guarding them does not exist.

WHY IT IS WORTH DELETING RATHER THAN LEAVING. It cost me an hour today: I read
ToggleButton, believed it was live, and told him something false about his own
panel. Dead code is not free - it is a false statement about how the program
works, kept somewhere people go to find out how the program works. That is the
same defect as a log line announcing work it does not do, which is most of what
this repository has been fixing today.

SETTLED SINCE (2026-09-25). ToggleButton and the ControlView branch that
added it were left here because their reachability turned on a runtime
condition: whether a message carrying action buttons is ever NOT the admin
panel. It is not - every such view is built by admin_control_view() and
delivered as an ephemeral followup, which is exactly what
is_private_panel_message() calls private. Five months of recorded presses
agree: 47 on a Discord button, every one start, stop or restart. Both are
gone, with the proof in
tests/spec/test_a_panel_never_offers_to_expand.py and
tests/spec/test_a_registered_button_is_on_a_posted_view.py.

HOW THIS TEST CAN FAIL: the per-container message code coming back.

COUNTER-CHECK (2026-09-25): red before - all four names were present.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
COGS = PROJECT / "cogs"

# Gone, with the number of callers each had when it was removed.
THE_OLD_DESIGN = {
    "send_server_status": "sent one message per container",
    "_edit_single_message": "edited one container's own message",
    "_edit_single_message_wrapper": "the retry wrapper around it",
}
# Never assigned anywhere; four reads all sat behind hasattr().
THE_ATTRIBUTE_THAT_NEVER_WAS = "tracked_status_messages"


def _defined_functions():
    for path in sorted(COGS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield path.relative_to(PROJECT), node.name


def test_nothing_sends_or_edits_a_per_container_message():
    """THE FINDING: 319 lines the edit loop would delete on sight."""
    found = [f"{path}: {name}() - {THE_OLD_DESIGN[name]}"
             for path, name in _defined_functions() if name in THE_OLD_DESIGN]

    assert sorted(found) == [], (
        "the per-container design is back, and the periodic edit loop deletes "
        f"its tracking as a phantom: {sorted(found)}")


def test_nothing_reads_an_attribute_that_is_never_set():
    """Four reads, all guarded by hasattr(), and no assignment anywhere - so
    two loops sat there looking like working code and could not run."""
    offenders = []
    for path in sorted(COGS.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute) and node.attr == THE_ATTRIBUTE_THAT_NEVER_WAS:
                offenders.append(f"{path.relative_to(PROJECT)}:{node.lineno}")
            if isinstance(node, ast.Constant) and node.value == THE_ATTRIBUTE_THAT_NEVER_WAS:
                offenders.append(f"{path.relative_to(PROJECT)}:{node.lineno}")

    assert sorted(set(offenders)) == [], (
        f"{THE_ATTRIBUTE_THAT_NEVER_WAS} is read again but still never set: "
        f"{sorted(set(offenders))}")


def test_the_edit_loop_still_refuses_anything_but_the_two_overviews():
    """The rule this rests on. If the loop ever started handling per-container
    names, the deletions above would have removed something needed."""
    source = (COGS / "message_updates.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.value for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and node.value in ("overview", "admin_overview")}

    assert names == {"overview", "admin_overview"}, names
    assert "phantom" in source, (
        "the loop no longer discards per-container tracking, so the design "
        "this test rests on has changed")


def test_the_overview_path_is_untouched():
    """The opposite mistake: deleting the live path with the dead one. These
    are what actually draws the operator's two panels."""
    present = {name for _path, name in _defined_functions()}

    for needed in ("_generate_status_embed_and_view", "periodic_message_edit_loop",
                   "_regenerate_channel"):

        assert needed in present, f"{needed} went with the dead code"
