# -*- coding: utf-8 -*-
"""The ✕ never stands alone on a row; such a panel closes itself instead.

THE OPERATOR (2026-09-27), with a screenshot of the admin container picker -
a select, and under it the ✕ on a row of its own: "can't that go in one
line? Otherwise put an auto close after one minute and delete the close
button; the close button should never stand alone on a row."

It cannot go on one line: Discord gives a select a whole row, and nothing
sits beside it. So wherever the ✕ would end up alone - after a select, or
after a full row of five buttons - it is left out, and the panel removes
itself after a minute.

AND THE MINUTE MUST NOT TAKE THE NEXT PANEL WITH IT. The picker turns into
the container's admin panel by editing the same message; its own timer used
to run on (180 s back then) and deleted whatever the message showed by then.
A view whose message has been given another view leaves it alone.

COUNTER-CHECK (2026-09-27): red before - the picker had its lone ✕ and a
three-minute timer, and a replaced view deleted the message.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.ddc_ui import AUTO_CLOSE_SECONDS, CloseButton, PrivateView


def _has_close(view):
    return any(isinstance(item, CloseButton) for item in view.children)


class _SelectOnly(PrivateView):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(discord.ui.Select(options=[discord.SelectOption(label="a")]))


class _SelectAndButton(PrivateView):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(discord.ui.Select(options=[discord.SelectOption(label="a")]))
        self.add_item(discord.ui.Button(label="b"))


class _FiveButtons(PrivateView):
    def __init__(self):
        super().__init__(timeout=180)
        for n in range(5):
            self.add_item(discord.ui.Button(label=str(n)))


@pytest.mark.asyncio
async def test_a_select_alone_gets_no_close_button_but_closes_itself():
    view = _SelectOnly()
    assert not _has_close(view), "the ✕ stands alone under the select"
    assert view.timeout == AUTO_CLOSE_SECONDS == 60


@pytest.mark.asyncio
async def test_a_full_row_of_buttons_gets_no_lone_close_button():
    view = _FiveButtons()
    assert not _has_close(view)
    assert view.timeout == AUTO_CLOSE_SECONDS


@pytest.mark.asyncio
async def test_a_close_button_with_company_stays():
    view = _SelectAndButton()
    assert _has_close(view)
    assert view.timeout == 180
    rows = view.to_components()
    close_row = next(r for r in rows if any(c.get("custom_id") == "ddc_close_panel" for c in r["components"]))
    assert len(close_row["components"]) == 2


def _message(view_on_it):
    store = SimpleNamespace(_synced_message_views={42: view_on_it})
    return SimpleNamespace(id=42, _state=SimpleNamespace(_view_store=store), delete=AsyncMock(),
                           flags=SimpleNamespace(ephemeral=True))


@pytest.mark.asyncio
async def test_a_replaced_view_does_not_delete_the_new_panel(monkeypatch):
    monkeypatch.setattr("cogs.ddc_ui.is_private_panel_message", lambda _m: True)
    old = _SelectOnly()
    old.message = _message(view_on_it=object())  # the admin panel now lives on it
    await old.on_timeout()
    old.message.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_its_own_message_is_still_removed(monkeypatch):
    monkeypatch.setattr("cogs.ddc_ui.is_private_panel_message", lambda _m: True)
    view = _SelectOnly()
    view.message = _message(view_on_it=view)
    await view.on_timeout()
    view.message.delete.assert_awaited_once()
