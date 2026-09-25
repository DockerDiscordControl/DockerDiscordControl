# -*- coding: utf-8 -*-
"""A private panel that has run out of time removes itself.

THE OPERATOR (2026-09-25), with a screenshot of his admin panel: "can we edit
or delete ephemeral messages in Discord? At the moment one message builds up
after another, and when the process is finished I have to remove every one of
them by hand with 'Dismiss message'."

Yes to both, and py-cord 2.6.1 in the running image has everything needed -
delete_after on an ephemeral send, Interaction.delete_original_response, and it
attaches the sent message to the view by itself (interactions.py:528,
webhook/async_.py:2014). DDC used none of it: across cogs/ there were 262
ephemeral sends and ZERO deletions.

WORSE THAN CLUTTER, and this is the part he could not see: AdminContainerSelectView
and ContainerInfoSelectView carry timeout=180 and had no on_timeout at all. Three
minutes after opening, py-cord stops listening - so the dropdown silently stops
working while the message sits there looking perfectly usable, and the only way
to be rid of it is to dismiss it by hand. A dead panel that still looks alive is
the same species as a log line that announces work it does not do.

THE DANGEROUS HALF of this change, and why the guard matters more than the
deletion: a view's timeout firing must NEVER remove a message everybody can
see. The public overview and every Mech view are persistent (timeout=None), so
on_timeout cannot fire for them today - but "cannot fire today" is a property
of thirteen separate constructor calls, and one of them only has to change. So
the base class asks the message itself whether it is private, with the same
flags check the admin-panel detection uses, and a public message is left alone
whatever its timeout says.

DELIBERATELY NOT CHANGED: DonationView, ContainerInfoAdminView and LiveLogView
already define on_timeout and keep it. LiveLogView's greys its buttons out and
sets a footer saying to run /info again, which is information rather than
clutter; overriding that here would be deciding a UI question inside a base
class. Their panels still have to be dismissed by hand, and the operator knows.

HOW THIS TEST CAN FAIL: a private panel outliving its own view, or - far worse
- a public one being deleted by a timeout.

COUNTER-CHECK (2026-09-25): red before - DDCView had no on_timeout, so the case
that lets a private panel time out found the message still there.
"""

import asyncio
from types import SimpleNamespace

import pytest

from cogs.ddc_ui import DDCView


class _Message:
    """A Discord message that records whether deletion was even ATTEMPTED.

    Both numbers matter and they are different questions: `attempts` says
    whether the guard let it through, `deleted` whether Discord accepted it.
    A case that only looked at `deleted` could not tell "left alone on
    purpose" from "tried and failed".
    """

    def __init__(self, ephemeral, raises=None):
        self.flags = None if ephemeral is None else SimpleNamespace(ephemeral=ephemeral)
        self.attempts = 0
        self.deleted = False
        self._raises = raises

    async def delete(self):
        self.attempts += 1
        if self._raises is not None:
            raise self._raises
        self.deleted = True


_NOTHING_WAS_SENT = object()


def _timed_out(message=_NOTHING_WAS_SENT):
    """Build a view, give it this message, and let its timeout fire.

    The view is constructed INSIDE the coroutine: discord.ui.View.__init__
    calls asyncio.get_running_loop(), which needs a loop that is actually
    running - setting one with set_event_loop is not enough, and a fixture
    that built the view outside failed with "no running event loop" on every
    case in the production image.
    """
    async def run():
        view = DDCView(timeout=180)
        if message is not _NOTHING_WAS_SENT:
            view.message = message
        await view.on_timeout()

    try:
        asyncio.run(run())
    except BaseException as error:        # noqa: BLE001 - the point of the call
        return error
    return None


def test_a_private_panel_is_taken_away():
    """THE FINDING: it used to sit there, dead, until dismissed by hand."""
    message = _Message(ephemeral=True)

    assert _timed_out(message) is None
    assert message.deleted is True


def test_a_public_panel_is_never_touched():
    """THE CASE THAT MATTERS MOST. The overview everyone reads is a message
    with a view on it. If a timeout could delete it, one changed constructor
    argument would empty an operator's status channel."""
    message = _Message(ephemeral=False)
    _timed_out(message)

    assert message.attempts == 0, "a timeout tried to delete a message everybody can see"
    assert message.deleted is False


def test_a_view_that_was_never_sent_does_not_crash():
    """py-cord only attaches the message once it has been sent. A view that
    timed out before that - or one built in a test - has no message."""
    assert _timed_out() is None, "a view that was never sent raised on timeout"


def test_a_message_already_gone_does_not_crash():
    """The operator may have dismissed it himself a second earlier, and the
    fifteen-minute interaction token may have expired. Neither is an error."""
    import discord

    message = _Message(ephemeral=True,
                       raises=discord.NotFound(
                           SimpleNamespace(status=404, reason="Not Found"), "gone"))

    assert _timed_out(message) is None, "a message that was already gone raised"
    assert message.attempts == 1, "it did not even try"


def test_the_flags_are_what_decide():
    """Read from the message, not from the view. A view does not know whether
    it was sent privately; the message carries the flag, which is the same
    thing the admin-panel detection asks (cogs/control_helpers.py)."""
    message = _Message(ephemeral=None)        # a message carrying no flags at all

    assert _timed_out(message) is None
    assert message.attempts == 0, "a message with no flags was treated as private"


def test_the_public_panels_are_still_persistent():
    """Counter-check on the guard's backstop: the views on messages everybody
    reads carry timeout=None, so on_timeout cannot fire for them at all. Both
    protections must hold, because the flags check is the only one left if
    this ever changes."""
    import ast
    from pathlib import Path

    project = Path(__file__).resolve().parents[2]
    public = {"AdminOverviewView", "ControlView", "StatusInfoView", "MechView"}
    found = set()
    for path in (project / "cogs").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and node.name in public:
                body = ast.unparse(node)

                assert "timeout=None" in body, f"{node.name} is no longer persistent"
                found.add(node.name)

    assert found == public, f"missing: {public - found}"
