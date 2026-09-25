# -*- coding: utf-8 -*-
"""A close button appears on private panels, and never on a public one.

THE OPERATOR (2026-09-25): "can we add a close button to the private panels
that have a button - I don't know whether everyone understands 'Dismiss
message'." He is right: that phrase is Discord's, not DDC's, and it is the
only way out of an ephemeral message until its view expires.

AND HIS SECOND MESSAGE IS THE WHOLE REASON THIS FILE EXISTS: "careful, the
main views in the status channel and the control channel must NOT get a close
button, only the private ephemeral messages."

WHY THAT WAS ALREADY THE DANGER. ControlView is built for the channel
overviews as well as for the admin panel:

    status_handlers.py:1123   the status and control channel overviews
    control_ui.py, group_control.py
                              the admin panel, sent as an ephemeral followup
                              and edited in place

A close button on the first would have appeared on the message everybody in
the channel reads, and one press would have deleted it for all of them. The
same class, the same buttons, a different audience.

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
# ToggleButton stood here too, as the expand/collapse control on the public
# panel. The operator said his panels have no expanding any more; that was
# proved on 2026-09-25 and the class was removed, so the scope went with it.
PUBLIC_VIEW_SCOPES = (
    ("cogs/status_handlers.py", None, "the channel overviews"),
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
    the channel overviews must never ask."""
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


def test_it_sits_with_the_other_buttons_and_carries_no_word():
    """THE OPERATOR, shown the panel (2026-09-25): "only the X, behind the
    Info button."

    IT STARTED AS A LABELLED BUTTON ON A ROW OF ITS OWN - "✖ Schließen"
    under ⏹️ 🔄 ℹ️ - because his first complaint was that "Dismiss message"
    is not obvious. The word turned out to be the wrong answer to that: it
    made the panel two rows tall and read as a fourth kind of thing next to
    three controls that say what they do with an icon alone.

    THEN THE ICON WAS WRONG TOO. As the ✖️ emoji it came out dark grey
    beside three blue neighbours - he asked whether there was a blue X to
    match. There is not, so it is written as a text symbol and drawn in the
    button's own white.

    So the rule is the row and the shape, not the word: the close button is
    the LAST item of the same row as the actions, and carries a single
    symbol that needs no translation. Built through the real factory,
    because a check on the class alone would not notice a call site putting
    it back on row 1.
    """
    import asyncio

    from cogs.group_control import admin_control_view

    async def build():
        cog = SimpleNamespace(pending_actions={}, expanded_states={})
        config = {"docker_name": "alpha", "name": "alpha",
                  "allowed_actions": ["stop", "restart"],
                  "allow_detailed_status": True}
        return admin_control_view(cog, config, is_running=True)

    view = asyncio.run(build())
    items = list(view.children)
    closing = items[-1]

    assert type(closing).__name__ == "CloseButton", [type(i).__name__ for i in items]

    # A SYMBOL AS THE LABEL, NOT AN EMOJI - and that is about colour, not
    # taste. Discord draws these controls with its own emoji set, which
    # colours ▶️ ⏹️ 🔄 ℹ️ blue and ✖️ dark grey; on the grey button the X
    # came out washed out beside its blue neighbours, and the operator said
    # so. There is no blue X in that set: the alternatives are ❌ (red) and
    # ❎ (green). A LABEL is drawn in the button's own white, so the X is
    # written as text instead.
    assert closing.emoji is None, f"an emoji is back: {closing.emoji}"
    assert closing.label == "\u2715", repr(closing.label)

    # Still no WORD, which is what he asked for: nothing here needs a
    # catalogue key, in any of the forty languages.
    assert not any(character.isalpha() for character in closing.label), repr(closing.label)

    rows = {item.row for item in items}

    assert rows == {0}, f"the panel is more than one row: {[(type(i).__name__, i.row) for i in items]}"

    # Discord fits five to a row. A container offers at most stop, restart and
    # info, so the fourth seat is the close button and one stays free.
    assert len(items) <= 5, len(items)


def test_the_word_it_used_to_carry_is_gone_from_the_catalogues():
    """The other half of removing a label: the key it read is left behind in
    forty files otherwise.

    ``"Close"`` is a bot-style key - the English sentence IS the key - which
    test_no_catalogue_key_is_read_by_nobody.py cannot sweep, because that one
    only handles the dotted ``web.…`` keys. It was added by the same commit
    that added the label (44872ffb) and had exactly one reader.
    """
    still_there = []
    for catalogue in sorted((PROJECT / "locales").glob("*.json")):
        if catalogue.name == "meta.json":
            continue
        words = json.loads(catalogue.read_text(encoding="utf-8"))
        if "Close" in words:
            still_there.append(catalogue.stem)

    assert still_there == [], (
        f"the label is gone but its key is still translated in: {still_there}")

    # The panel's own key is a different one and stays: it is read by five
    # templates (_diagnostics_modal.html and others).
    panel = json.loads((PROJECT / "locales" / "de.json").read_text(encoding="utf-8"))

    assert panel["web.common.close"] == "Schlie\u00dfen"
