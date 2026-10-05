# -*- coding: utf-8 -*-
"""The live-log panel keeps one title; its state is in the footer, in the bot's language.

THE FINDING (2026-10-05): the title said what had last happened - "🔍 Live
Logs", "📄 Logs", "🔄 Debug Logs", "⏹️ Debug Logs", "▶️ Live Logs" - and named
the container by its display name when opened and by its Docker name after
the first press. Footers were built in five places, and the texts that come
back instead of log lines ("Container 'x' not found.", "Error retrieving
logs: ...") were English for every server.

THE CONTRACT: "📋 <display name>" whatever happens; the footer tells live,
ended and still apart; those texts and the error texts go through the
catalogue (the catalogue test checks the keys).

HOW THIS TEST CAN FAIL: a press or a live update that draws another title,
or a footer that does not change with the state.

COUNTER-CHECK (2026-10-05): red on the code before the change (no log_embed;
a press drew "🔄 Debug Logs - nginx").
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.status_info_integration as sii

TITLE = "📋 Valheim Server"
SPAM = "services.infrastructure.spam_protection_service.get_spam_protection_service"


def _press():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_one_title_and_a_footer_per_state():
    view = sii.LiveLogView("valheim", display_name="Valheim Server")
    still = view.log_embed("x")
    view.auto_refresh_enabled = True
    live = view.log_embed("x")
    view.auto_refresh_enabled, view._ended = False, True
    ended = view.log_embed("x")

    assert [e.title for e in (still, live, ended)] == [TITLE] * 3
    assert len({e.footer.text for e in (still, live, ended)}) == 3, "the footer does not show the state"


@pytest.mark.asyncio
async def test_a_press_keeps_the_title(monkeypatch):
    monkeypatch.setattr(sii, "container_logs_text", AsyncMock(return_value="line"))
    view = sii.LiveLogView("valheim", display_name="Valheim Server")
    refresh, start, stop = _press(), _press(), _press()
    with patch(SPAM, return_value=SimpleNamespace(is_enabled=lambda: False)):
        await view.manual_refresh(refresh)
        await view.toggle_updates(start)
        await view.toggle_updates(stop)

    for press in (refresh, start, stop):
        assert press.edit_original_response.await_args.kwargs["embed"].title == TITLE
