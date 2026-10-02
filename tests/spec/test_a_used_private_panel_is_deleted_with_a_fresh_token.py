# -*- coding: utf-8 -*-
"""A private panel that was used is deleted with the token of its last press.

THE FINDING (operator's question, 2026-10-02: are private panels deleted
reliably before Discord's fifteen minutes run out?): no. Every press starts
a view's timeout again, but DDC deleted the panel with the token of the
message it was SENT with - fifteen minutes from the first answer. A panel
used for a while timed out after that token had died, the delete failed,
and only a debug line said so.

THE CONTRACT: a press whose response is the panel itself (a deferred update
or an edit - not a new message, not a modal) leaves its interaction behind
as the panel's deleter; the timeout deletes through it, a fresh fifteen
minutes. Without such a press the message the panel was sent with is used,
as before.

HOW THIS TEST CAN FAIL: the timeout deletes with the first token again, or
with a press whose original response is another message.

COUNTER-CHECK (2026-10-02): red before the change (the first message's
delete was used).
"""

from types import SimpleNamespace

import pytest

from cogs.ddc_ui import PrivateView

PANEL_ID = 55


class _Panel(PrivateView):
    def __init__(self):
        super().__init__(timeout=300)


def _panel_message(deleted):
    async def delete():
        deleted.append("first token")
    return SimpleNamespace(id=PANEL_ID, flags=SimpleNamespace(ephemeral=True), delete=delete, _state=None)


def _press(original_id, deleted):
    async def original_response():
        return SimpleNamespace(id=original_id)

    async def delete_original_response():
        deleted.append(f"press answered with {original_id}")
    return SimpleNamespace(message=SimpleNamespace(id=PANEL_ID, flags=SimpleNamespace(ephemeral=True)),
                           original_response=original_response,
                           delete_original_response=delete_original_response)


def _item():
    async def callback(interaction):
        return None
    return SimpleNamespace(callback=callback)


@pytest.mark.asyncio
async def test_the_timeout_uses_the_press_that_answered_on_the_panel():
    deleted = []
    view = _Panel()
    view._sent_message = _panel_message(deleted)
    await view._scheduled_task(_item(), _press(PANEL_ID, deleted))
    await view.on_timeout()
    assert deleted == [f"press answered with {PANEL_ID}"]


@pytest.mark.asyncio
async def test_a_press_that_answered_elsewhere_is_not_used():
    deleted = []
    view = _Panel()
    view._sent_message = _panel_message(deleted)
    await view._scheduled_task(_item(), _press(999, deleted))     # a new message, say
    await view.on_timeout()
    assert deleted == ["first token"]
