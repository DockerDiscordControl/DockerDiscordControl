# -*- coding: utf-8 -*-
"""Which panel a button sits on is state, not a word in a translated title.

THE OPERATOR'S REPORT (2026-09-24, second time): he pressed the start button on
a container group. The group started - the overview said 2/2 - and the panel
redrew itself as

    ⚠️ <group name>
    Error: Could not retrieve status. Configuration missing or initial
    fetch failed.

(he reads it in German, which is the whole point of what follows)

The first fix gave the two panel builders one builder. It did not help, and the
log says why:

    17:57:20  START action for 'Icaruse' ... success=True
    17:58:02  [_GEN_EMBED] No server configuration found for 'Icaruse'
    17:58:02  [ACTION_BTN] Updated control message for Icaruse

"Updated control message" - the NORMAL branch, not the admin branch, although
the panel he pressed was the admin panel. The branch is chosen by

    is_admin_message = "Admin Control" in str(embed_title)

THE TITLE IS TRANSLATED. Measured across the catalogues, the English literal
appears in exactly ONE of the forty:

    en    "🛠️ Admin Control: {name}"                  matches
    de    "🛠️ Admin-Steuerung: {name}"                does not
    fr    "🛠️ Contrôle admin : {name}"                does not
    ja    "🛠️ 管理者コントロール: {name}"                 does not

So for every operator who does not run the bot in English - this one runs it in
German - a press in the admin panel has ALWAYS taken the normal branch. For a
container that branch still draws something sensible, which is why it went
unnoticed. For a group it asks the container machinery about a name no
container has, and that is the error he is looking at.

THE SAME HEURISTIC HAS BEEN REMOVED THREE TIMES ALREADY, each time because it
decided something it had no business deciding: the channel permission check
(control_ui.py, 2026-09-16, an old panel kept working after the right was
withdrawn) and twice more at :1019/:1072, where it decided whether a view
carrying a path to delete_task() was built (2026-09-17, SPEC.md Z5 and B1).
This is the fourth survivor. It steers which message is redrawn.

THE FIRST REPLACEMENT WAS ALSO WRONG, and it is written down here because it
cost the operator another round trip. I had it ask whether the message was the
tracked admin overview, reasoning that the 🛠️ button edits that message in
place. IT DOES NOT. The button sends a container dropdown as an EPHEMERAL
followup (cogs/admin_overview.py), and picking one replaces that ephemeral
message with the panel - so the panel is a message of its own, its id is not
the tracked one, and the new check answered "no" exactly as the title one had.
I read the callback that DEFERS and concluded from it; I had not read the
callback that SENDS.

WHAT IT ASKS NOW IS THE MESSAGE ITSELF. Ephemeral means sent to one person,
which is precisely the panels that redraw themselves; a channel's control
message is permanent and never ephemeral. No text, no language, nothing to keep
in step - and the flag belongs to the message, so it survives a restart, which
is the one thing the title ever had going for it.

HOW THIS TEST CAN FAIL: a panel deciding what it is by its own rendered text.

COUNTER-CHECK (2026-09-24): red before - the scan named control_ui.py:586 and
the helper did not exist. THE SECOND VERSION WAS GREEN AND WRONG: its cases
built the tracking themselves, so they proved that a lookup works and never
that the panel is in it. A test whose fixture agrees with the code about a
fact neither of them checked is the defect this suite hunts, and I wrote one.
The cases now pass the thing the press actually holds. Then three sabotages on the green baseline: the title
heuristic put back (1 red), the id compared without int() (1 red), and the
channel lookup made to fall back to any other channel - WHICH STAYED GREEN. The
cases only ever asked about two channels that were both tracked, so a lookup
that borrowed another channel's answer when this one was unknown passed. The
missing case is now there, and that sabotage is red too.
"""

import json
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
SOURCES = ("cogs", "services", "app", "utils")
TITLE_KEY = "🛠️ Admin Control: {name}"


class _Message:
    """A message, as the press sees it: it knows whether it is ephemeral."""

    def __init__(self, ephemeral):
        self.flags = type("Flags", (), {"ephemeral": ephemeral})()


def test_a_private_panel_is_recognised():
    from cogs.control_helpers import is_private_panel_message

    assert is_private_panel_message(_Message(True)) is True


def test_the_channels_own_message_is_not():
    """THE CASE BOTH WRONG ANSWERS GOT BACKWARDS: a control message in a
    channel is permanent, the panel is not."""
    from cogs.control_helpers import is_private_panel_message

    assert is_private_panel_message(_Message(False)) is False


def test_a_message_that_is_not_there_is_not_a_panel():
    """A press can arrive without one, and an exception here loses the redraw
    entirely."""
    from cogs.control_helpers import is_private_panel_message

    assert is_private_panel_message(None) is False


def test_a_message_without_flags_is_survived():
    from cogs.control_helpers import is_private_panel_message

    class _Bare:
        pass

    assert is_private_panel_message(_Bare()) is False


def test_nothing_is_asked_of_the_cog_any_more():
    """The tracked-id answer is gone rather than left beside the new one: two
    questions that can disagree is how this went wrong twice."""
    import inspect

    from cogs.control_helpers import is_private_panel_message

    source = inspect.getsource(is_private_panel_message)

    assert "channel_server_message_ids" not in source
    assert "admin_overview" not in source


def test_the_title_this_used_to_match_is_translated():
    """THE MEASUREMENT BEHIND THE FINDING: the literal the old check looked for
    exists in one catalogue out of forty, so the check was a language test."""
    catalogues = [p for p in sorted((PROJECT / "locales").glob("*.json"))
                  if p.name != "meta.json"]

    assert len(catalogues) >= 39, f"only {len(catalogues)} catalogues found"
    carrying = [p.name for p in catalogues
                if "Admin Control" in json.loads(p.read_text(encoding="utf-8")).get(TITLE_KEY, "")]

    assert carrying == ["en.json"], (
        f"the English literal appears in {len(carrying)} catalogues: {carrying}")


def test_no_code_decides_anything_by_that_title():
    """THE RATCHET. Three earlier removals were each made where the symptom
    was; this is the fourth site of the same heuristic. A fifth is a scan away.

    IT FLAGS A DECISION, NOT AN OCCURRENCE. Written as a search for the
    characters it found three innocents - the catalogue key "Admin Control
    Panel", two log lines, and the docstring in control_helpers.py that
    explains one of the earlier removals. A scan that cries wolf four times
    for every real hit teaches whoever reads it to skip the result, so this one
    reads the SYNTAX TREE and reports the literal only where it is an operand
    of a comparison or a membership test - which is what "deciding by the
    title" is.
    """
    import ast

    offenders = []
    for root in SOURCES:
        for path in sorted((PROJECT / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                operands = []
                if isinstance(node, ast.Compare):
                    operands = [node.left, *node.comparators]
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("startswith", "endswith", "find", "index",
                                               "count", "__contains__")):
                    operands = list(node.args)
                for operand in operands:
                    if (isinstance(operand, ast.Constant)
                            and isinstance(operand.value, str)
                            and "Admin Control" in operand.value):
                        offenders.append(
                            f"{path.relative_to(PROJECT).as_posix()}:{node.lineno} "
                            f"{ast.unparse(node)[:70]}")

    assert offenders == [], (
        "these decide something by matching a translated title:\n  "
        + "\n  ".join(offenders))


def test_the_button_asks_the_message():
    """The call site, read from the syntax tree rather than from a word that
    also appears in the comment above it - and it must be handed the MESSAGE,
    not an id, or we are back at looking the panel up somewhere else."""
    import ast

    source = (PROJECT / "cogs" / "control_ui.py").read_text(encoding="utf-8")
    calls = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call)
             and "is_private_panel_message" in ast.unparse(node.func)]

    assert calls, "control_ui.py no longer asks which panel the press is on"
    for call in calls:
        argument = ast.unparse(call.args[0]) if call.args else ""

        assert "message" in argument, (
            f"asked about {argument!r} instead of the message itself")
