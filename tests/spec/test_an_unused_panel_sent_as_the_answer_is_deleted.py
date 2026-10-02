# -*- coding: utf-8 -*-
"""A private panel sent as the answer itself is deleted even if nobody pressed it.

THE FINDING (2026-10-02, while answering the operator's question about
private panels): py-cord hands a view its message when the panel goes out
as a followup, but for interaction.response.send_message(view=...) it only
sets view.parent - the interaction. DDCView.on_timeout found no message and
returned, so such a panel that nobody pressed was never deleted: the
private /donate panel and the watchdog maintenance panel.

THE CONTRACT: without a message, a private panel's timeout deletes it
through view.parent - the answer to that interaction IS the panel.

HOW THIS TEST CAN FAIL: an unpressed panel sent as the answer stays again,
or a view that is not private deletes an answer.

COUNTER-CHECK (2026-10-02): red before the change (nothing deleted).
"""

from types import SimpleNamespace

import pytest

from cogs.ddc_ui import DDCView, PrivateView


class _Private(PrivateView):
    def __init__(self):
        super().__init__(timeout=300)


class _Public(DDCView):
    def __init__(self):
        super().__init__(timeout=300)


def _interaction(deleted):
    async def delete_original_response():
        deleted.append("answer deleted")
    return SimpleNamespace(delete_original_response=delete_original_response)


@pytest.mark.asyncio
async def test_the_private_answer_goes():
    deleted = []
    view = _Private()
    view.parent = _interaction(deleted)
    await view.on_timeout()
    assert deleted == ["answer deleted"]


@pytest.mark.asyncio
async def test_a_public_answer_stays():
    deleted = []
    view = _Public()
    view.parent = _interaction(deleted)
    await view.on_timeout()
    assert deleted == []
