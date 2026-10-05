# -*- coding: utf-8 -*-
"""The live-log panel keeps the timeout the panel sets, and then it goes.

THE FINDING (operator's question, 2026-10-05: "is the live log flawless?"):
the setting "Message timeout (s)" (DDC_LIVE_LOGS_TIMEOUT, 30-600, said to
delete the log messages) was read in LiveLogView.__init__ and dropped. The
view had a fixed 300 s and rebuilt itself at 270 s with a fresh view, so it
never timed out; its own on_timeout only greyed the buttons. Fifteen minutes
after the panel was opened Discord refused the next rebuild, and a dead panel
stayed until dismissed by hand, against the v3.1.0 promise that private panels
close after at most ten minutes unused and are deleted.

This file replaces the one that guarded the rebuild (a renewed panel must not
be killed by the view it replaced): with no rebuild there is no predecessor.

THE CONTRACT: the timeout is the setting, held to 30-600 s; nothing renews the
panel behind the user's back; at the timeout the panel is deleted, as every
private panel is (DDCView.on_timeout), and a running live update stops.

HOW THIS TEST CAN FAIL: a fixed timeout, a renewal task started by the view,
or an on_timeout that edits instead of deleting.

COUNTER-CHECK (2026-10-05): all four cases red on the code before the change
(timeout 300 for every setting, one task started at construction, the
timed-out panel edited and kept).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.status_info_integration as sii


def _settings(**values):
    def get_setting(key, default, value_type=int):
        return values.get(key, default)
    return patch("utils.settings.get_setting", side_effect=get_setting)


class _Panel:
    """A private message that records whether it was deleted or edited."""

    def __init__(self):
        self.flags = SimpleNamespace(ephemeral=True)
        self.embeds = []
        self.deleted = False
        self.edit = AsyncMock()

    async def delete(self):
        self.deleted = True


@pytest.mark.asyncio
@pytest.mark.parametrize("setting, timeout", [(45, 45), (120, 120), (5000, 600), (1, 30)])
async def test_the_timeout_is_the_setting(setting, timeout):
    with _settings(DDC_LIVE_LOGS_TIMEOUT=setting):
        view = sii.LiveLogView("nginx")

    assert view.timeout == timeout, (
        f"setting {setting} s gave a panel timeout of {view.timeout} s, not {timeout}")


@pytest.mark.asyncio
async def test_nothing_renews_the_panel():
    before = len(asyncio.all_tasks())
    sii.LiveLogView("nginx")
    await asyncio.sleep(0)

    assert len(asyncio.all_tasks()) == before, (
        "building the panel started a task: something renews it behind the user's back")


@pytest.mark.asyncio
async def test_at_its_timeout_the_panel_is_deleted_and_the_live_update_stops(monkeypatch):
    monkeypatch.setattr(sii, "container_logs_text", AsyncMock(return_value="x"))
    view = sii.LiveLogView("nginx", auto_refresh=True)
    panel = _Panel()
    view.message = panel
    view.message_ref = panel
    live = MagicMock()
    view.auto_refresh_task = live

    await view.on_timeout()

    assert panel.deleted, "the timed-out live-log panel stayed"
    panel.edit.assert_not_awaited()
    live.cancel.assert_called_once()
    assert view.auto_refresh_enabled is False
