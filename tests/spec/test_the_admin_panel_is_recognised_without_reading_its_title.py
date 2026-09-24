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

WHAT REPLACES IT IS ALREADY IN THE COG. The admin panel is not a message of its
own - the 🛠️ button edits the admin overview message in place - and the cog
tracks that message's id per channel in ``channel_server_message_ids``, which
is persisted and restored on startup (docker_control.py). Asking it is exact,
carries no language, and survives a restart, which is the only reason the title
was read in the first place.

HOW THIS TEST CAN FAIL: a panel deciding what it is by its own rendered text.

COUNTER-CHECK (2026-09-24): red before - the scan named control_ui.py:586 and
the helper did not exist. Then three sabotages on the green baseline: the title
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


def _cog(tracked):
    """A stand-in carrying only what the question needs: the tracked ids."""
    class _Cog:
        channel_server_message_ids = tracked

    return _Cog()


def test_the_tracked_admin_message_is_the_admin_panel():
    from cogs.control_helpers import is_admin_panel_message

    cog = _cog({4711: {"overview": 111, "admin_overview": 222}})

    assert is_admin_panel_message(cog, 4711, 222) is True


def test_another_message_in_the_same_channel_is_not():
    """The server overview lives in the same channel and carries buttons too."""
    from cogs.control_helpers import is_admin_panel_message

    cog = _cog({4711: {"overview": 111, "admin_overview": 222}})

    assert is_admin_panel_message(cog, 4711, 111) is False
    assert is_admin_panel_message(cog, 4711, 999) is False


def test_the_same_id_in_another_channel_is_not():
    """Ids are unique to Discord, but the lookup is per channel and must not
    answer out of the wrong one."""
    from cogs.control_helpers import is_admin_panel_message

    cog = _cog({4711: {"admin_overview": 222}, 4712: {"admin_overview": 333}})

    assert is_admin_panel_message(cog, 4712, 222) is False


def test_an_untracked_channel_does_not_borrow_another_channel_s_answer():
    """FOUND BY SABOTAGE (2026-09-24): the case above only proves the lookup
    picks the right entry when BOTH channels are tracked. Replacing the lookup
    with "this channel, or else the first one we know" left every case green -
    a bot with one tracked channel would then have called every message in
    every other channel the admin panel."""
    from cogs.control_helpers import is_admin_panel_message

    cog = _cog({4711: {"admin_overview": 222}})

    assert is_admin_panel_message(cog, 9999, 222) is False


@pytest.mark.parametrize("tracked", [{}, {4711: {}}, {4711: {"admin_overview": None}}])
def test_nothing_tracked_is_not_the_admin_panel(tracked):
    """An untracked channel must answer "no", not raise - this runs inside a
    button press, and an exception there loses the redraw entirely."""
    from cogs.control_helpers import is_admin_panel_message

    assert is_admin_panel_message(_cog(tracked), 4711, 222) is False


def test_a_cog_without_the_attribute_is_survived():
    """Registration-only cog instances exist (bot.add_view builds views with a
    bare cog); the question must hold for them too."""
    from cogs.control_helpers import is_admin_panel_message

    class _Bare:
        pass

    assert is_admin_panel_message(_Bare(), 4711, 222) is False


def test_the_id_is_compared_as_a_number():
    """The tracked ids are restored from JSON, where a key can come back as a
    string. A comparison that fails on the type would say "not the admin
    panel" for every restored channel after a restart - the exact case the
    tracking exists for."""
    from cogs.control_helpers import is_admin_panel_message

    assert is_admin_panel_message(_cog({4711: {"admin_overview": "222"}}), 4711, 222) is True


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


def test_the_button_asks_the_cog_instead():
    """The call site, read from the syntax tree rather than from a word that
    also appears in the comment above it."""
    import ast

    source = (PROJECT / "cogs" / "control_ui.py").read_text(encoding="utf-8")
    called = {ast.unparse(node.func) for node in ast.walk(ast.parse(source))
              if isinstance(node, ast.Call)}

    assert any("is_admin_panel_message" in name for name in called), (
        "control_ui.py no longer asks the cog which message the admin panel is")
