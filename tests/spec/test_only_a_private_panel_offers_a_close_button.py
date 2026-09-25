# -*- coding: utf-8 -*-
"""A close button appears on private panels, and never on a public one.

THE OPERATOR (2026-09-25): "can we add a close button to the private panels
that have a button - I don't know whether everyone understands 'Dismiss
message'." He is right: that phrase is Discord's, not DDC's, and it is the
only way out of an ephemeral message until its view expires.

AND HIS SECOND MESSAGE IS THE WHOLE REASON THIS FILE EXISTS: "careful, the
main views in the status channel and the control channel must NOT get a close
button, only the private ephemeral messages."

WHY THAT WAS ALREADY THE DANGER. ControlView is built at five places, and only
two of them are private:

    status_handlers.py:965, :1123   the status and control channel overviews
    control_ui.py:1030              inside ToggleButton - the expand/collapse
                                    control on the PUBLIC overview, which
                                    rebuilds the button row in place
    control_ui.py:593, :2205        the admin panel, sent as an ephemeral
                                    followup and edited in place

A close button on any of the first three would have appeared on the message
everybody in the channel reads, and one press would have deleted it for all of
them. The same class, the same buttons, a different audience.

TWO GUARDS, because one line at one call site is exactly the kind of thing the
next person copies to the wrong place:

  * the button is only ADDED where the panel is private - by a line at that
    site rather than a flag ControlView carries, so a public site does not
    even mention it - and the public scopes are pinned here so adding it
    there turns this file red;
  * the button REFUSES when pressed on a message that is not ephemeral. It
    asks the message's own flag, the same one that decides whether an expired
    panel deletes itself (cogs/ddc_ui.py).

NOTHING WAS TRANSLATED BY HAND. All forty catalogues already carry a checked
"Close" under web.common.close - Schliessen, Fermer, Kapat - so the new key
takes those values rather than inventing forty new ones.

HOW THIS TEST CAN FAIL: a close button on a public view, or a private panel
left with no way out but Discord's own wording.

COUNTER-CHECK (2026-09-25): red before - no such button existed anywhere.
"""

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

PROJECT = Path(__file__).resolve().parents[2]
CONTROL_UI = PROJECT / "cogs" / "control_ui.py"

# Where a ControlView is built for a message EVERYBODY can see. BY ENCLOSING
# SCOPE, not by file: control_ui.py holds the two private admin sites as well,
# so forbidding the flag across that file flagged the very sites that are
# supposed to have it.
#
# ToggleButton is in the list although the operator pointed out, correctly,
# that his panels have no expand/collapse any more - `send_server_status` is
# called by no production code, so that button cannot appear today. It is
# named anyway because the rule is about what the class is FOR, and dead code
# has a way of coming back.
PUBLIC_VIEW_SCOPES = (
    ("cogs/status_handlers.py", None, "the channel overviews"),
    ("cogs/control_ui.py", "ToggleButton", "expand/collapse on the public panel"),
)


def _close_button():
    from cogs.ddc_ui import CloseButton

    return CloseButton


class _Message:
    """A message that refuses deletion the way Discord refuses it.

    AN EPHEMERAL MESSAGE IS NOT IN A CHANNEL. Message.delete() sends
    DELETE /channels/{id}/messages/{id}, which Discord answers 404 for one -
    so the first version of this button called it, the failure was swallowed
    by its own except clause, and the button silently did nothing while never
    acknowledging the press. The operator saw "DDC did not respond in time".

    The first version of THIS double just set a flag and returned, so it could
    not reproduce that. A double that cannot fail the way the real thing fails
    is not a test of anything.
    """

    def __init__(self, ephemeral):
        self.flags = SimpleNamespace(ephemeral=ephemeral)
        self.delete_attempted = False

    async def delete(self):
        self.delete_attempted = True
        if self.flags.ephemeral:
            raise discord.NotFound(
                SimpleNamespace(status=404, reason="Unknown Message"), "ephemeral")


class _Interaction:
    """An interaction that records whether it was ANSWERED.

    Discord gives three seconds. Deleting a message is not an answer, and the
    operator's screenshot is what that looks like.
    """

    def __init__(self, ephemeral):
        self.message = _Message(ephemeral)
        self.deferred = False
        self.original_deleted = False
        self.response = SimpleNamespace(defer=self._defer, is_done=lambda: self.deferred)

    async def _defer(self, *_args, **_kwargs):
        self.deferred = True

    async def delete_original_response(self, *_args, **_kwargs):
        if not self.deferred:
            raise AssertionError("deleted the response before acknowledging the press")
        self.original_deleted = True


def _press(ephemeral):
    """Build the button inside a loop and press it, as Discord would."""
    interaction = _Interaction(ephemeral)

    async def run():
        await _close_button()().callback(interaction)

    asyncio.run(run())
    return interaction


def test_pressing_it_takes_a_private_panel_away():
    """THE REQUEST: one obvious button instead of Discord's own wording."""
    interaction = _press(ephemeral=True)

    assert interaction.original_deleted is True


def test_the_press_is_acknowledged():
    """THE BUG THE FIRST VERSION SHIPPED. Discord gives three seconds; the
    button deleted a message and answered nothing, so it showed the operator
    "DDC did not respond in time" and the panel stayed."""
    interaction = _press(ephemeral=True)

    assert interaction.deferred is True, "the button never answered the press"


def test_it_does_not_use_the_channel_route():
    """The other half of the same bug. Message.delete() is the channel route,
    and an ephemeral message is not in a channel - the call fails, and an
    except clause swallowing it is what made this silent."""
    interaction = _press(ephemeral=True)

    assert interaction.message.delete_attempted is False, (
        "still deleting through the channel route, which cannot work here")


def test_pressing_it_never_removes_a_public_panel():
    """HIS WARNING, as a running check rather than a promise. If this button
    ever reaches the overview, pressing it must still do nothing."""
    interaction = _press(ephemeral=False)

    assert interaction.original_deleted is False, (
        "a close button deleted a message everybody in the channel reads")
    assert interaction.message.delete_attempted is False


def test_even_a_refusal_answers_the_press():
    """Counter-check: refusing by returning early would leave Discord waiting
    and show the same "did not respond" the operator photographed."""
    interaction = _press(ephemeral=False)

    assert interaction.deferred is True, "a refused press was never acknowledged"


def test_the_public_construction_sites_do_not_ask_for_one():
    """The first guard: the button is only added where it is asked for, and
    these three places must never ask."""
    offenders = []
    for path, scope, what in PUBLIC_VIEW_SCOPES:
        tree = ast.parse((PROJECT / path).read_text(encoding="utf-8"))
        if scope is None:
            bounds = [(0, 10 ** 9)]
        else:
            bounds = [(node.lineno, node.end_lineno) for node in ast.walk(tree)
                      if isinstance(node, ast.ClassDef) and node.name == scope]

            assert bounds, f"{scope} is gone from {path} - re-read this rule"

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or "CloseButton" not in ast.unparse(node):
                continue
            if not any(low <= node.lineno <= high for low, high in bounds):
                continue
            offenders.append(f"{path}:{node.lineno} ({what})")

    assert sorted(set(offenders)) == [], (
        f"a public overview would carry a close button: {sorted(set(offenders))}")


def test_the_admin_panel_does_ask_for_one():
    """Counter-check: passing it nowhere would satisfy the case above and
    leave the operator exactly where he started."""
    source = (PROJECT / "cogs" / "group_control.py").read_text(encoding="utf-8")
    factory = next((node for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "admin_control_view"), None)

    assert factory is not None, "the private panel has no factory to put it in"

    # THE CALL, NOT THE NAME. The first version asked whether "CloseButton"
    # appeared anywhere in the factory - and deleting the add_item line left
    # it GREEN, because the import above it still said the word. That is the
    # tenth sabotage today to survive a case of mine by keeping a name the
    # case was looking for, and the sixth where the text was never the point.
    attached = [node for node in ast.walk(factory)
                if isinstance(node, ast.Call)
                and ast.unparse(node.func).endswith("add_item")
                and any("CloseButton" in ast.unparse(a) for a in node.args)]

    assert attached, "the factory names CloseButton but never adds one"

    # ...and both private call sites go through that one factory, so the
    # button cannot go missing from the panel rebuilt after an action.
    callers = CONTROL_UI.read_text(encoding="utf-8").count("admin_control_view(")

    assert callers == 2, f"expected the two admin-panel sites, found {callers}"


def test_the_word_is_translated_everywhere():
    """A new string needs a key in all forty catalogues. These are not
    invented: every catalogue already carries a checked translation under
    web.common.close, and the new key takes that value."""
    missing = []
    for catalogue in sorted((PROJECT / "locales").glob("*.json")):
        if catalogue.name == "meta.json":
            continue
        words = json.loads(catalogue.read_text(encoding="utf-8"))
        if not words.get("Close"):
            missing.append(catalogue.stem)

    assert missing == [], f"no close button text in: {missing}"


def test_the_translation_matches_the_one_already_checked():
    """Counter-check on the case above: filling all forty with the English
    word would pass it and leave a German panel saying "Close"."""
    for name, expected in (("de", "Schließen"), ("fr", "Fermer"), ("ja", "閉じる")):
        words = json.loads((PROJECT / "locales" / f"{name}.json").read_text(encoding="utf-8"))

        assert words["Close"] == expected, f"{name}: {words['Close']!r}"
        assert words["Close"] == words["web.common.close"]
