# -*- coding: utf-8 -*-
"""A press on the live-log panel redraws it through its own token, without a note.

THE FINDING (2026-10-05): 🔄 and ▶️/⏹️ each answered with an extra private
note ("🔄 Refreshing logs...", "⏳ Updating...") and then edited the panel
through the WebhookMessage of the 📋 press that had opened it. That token dies
fifteen minutes after the opening: from then on every press only produced the
note, the panel stayed as it was, and the live update could not draw either.

THE CONTRACT: a press is answered by a deferred update (no new message), the
panel is redrawn through that press (edit_original_response), and the live
update started or continued after a press draws through the newest press.

HOW THIS TEST CAN FAIL: a note sent with response.send_message, or an edit
through the opening message instead of the press.

COUNTER-CHECK (2026-10-05): all three cases red on the code before the change
(the note was sent and message_ref.edit was used).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.status_info_integration as sii

SPAM = "services.infrastructure.spam_protection_service.get_spam_protection_service"


def _press():
    interaction = MagicMock()
    interaction.user.id = 1
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


def _view(monkeypatch, **kw):
    monkeypatch.setattr(sii, "container_logs_text", AsyncMock(return_value="line"))
    view = sii.LiveLogView("nginx", **kw)
    view.message_ref = SimpleNamespace(edit=AsyncMock(), id=1)
    return view


def _no_brake():
    return patch(SPAM, return_value=SimpleNamespace(is_enabled=lambda: False))


def _drawn_through_the_press(view, press):
    press.response.send_message.assert_not_awaited()
    press.response.defer.assert_awaited_once()
    press.edit_original_response.assert_awaited()
    assert press.edit_original_response.await_args.kwargs["view"] is view
    view.message_ref.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_redraws_through_the_press(monkeypatch):
    view = _view(monkeypatch)
    press = _press()
    with _no_brake():
        await view.manual_refresh(press)

    _drawn_through_the_press(view, press)


@pytest.mark.asyncio
async def test_start_and_stop_redraw_through_the_press(monkeypatch):
    view = _view(monkeypatch)
    start, stop = _press(), _press()
    with _no_brake():
        await view.toggle_updates(start)
        _drawn_through_the_press(view, start)
        await view.toggle_updates(stop)

    _drawn_through_the_press(view, stop)
    assert view.auto_refresh_enabled is False


@pytest.mark.asyncio
async def test_the_live_update_draws_through_the_newest_press(monkeypatch):
    view = _view(monkeypatch)
    view.refresh_interval, view.max_refreshes = 0, 1
    press = _press()
    with _no_brake():
        await view.toggle_updates(press)
    press.edit_original_response.reset_mock()

    await view.auto_refresh_task

    press.edit_original_response.assert_awaited()
    view.message_ref.edit.assert_not_awaited()
