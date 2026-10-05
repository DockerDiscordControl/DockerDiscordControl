# -*- coding: utf-8 -*-
"""Live updates end while the live-log panel can still be deleted.

THE FINDING (2026-10-05): the panel's settings allow live updates every 30 s,
100 times: fifty minutes. An ephemeral panel can only be edited and deleted
with an interaction token, and a token lives fifteen minutes. From minute
fifteen every live edit failed, the loop broke off, and the panel stayed with
its live footer, beyond the reach of its own timeout.

THE CONTRACT: the live update stops at the latest when one more timeout would
no longer fit into the token's life (with 30 s to spare); its last drawing
says it has ended and shows ▶️ again; and every drawing leaves room for the
timeout's deletion before the token dies.

HOW THIS TEST CAN FAIL: drawings after minute 14:30 minus the timeout, or a
last drawing that still announces more updates.

COUNTER-CHECK (2026-10-05): red with the window switched off (100 drawings,
the last at 50 minutes).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import cogs.status_info_integration as sii

TOKEN_LIFE = 15 * 60


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _settings(**values):
    def get_setting(key, default, value_type=int):
        return values.get(key, default)
    return patch("utils.settings.get_setting", side_effect=get_setting)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [30, 120, 600])
async def test_the_last_live_drawing_leaves_room_for_the_deletion(monkeypatch, timeout):
    clock = _Clock()
    monkeypatch.setattr(sii, "monotonic", clock)
    monkeypatch.setattr(sii, "container_logs_text", AsyncMock(return_value="line"))

    async def sleep(seconds):
        clock.now += seconds
    monkeypatch.setattr("asyncio.sleep", sleep)

    with _settings(DDC_LIVE_LOGS_TIMEOUT=timeout, DDC_LIVE_LOGS_REFRESH_INTERVAL=30,
                   DDC_LIVE_LOGS_MAX_REFRESHES=100):
        view = sii.LiveLogView("nginx", auto_refresh=True)
    drawings = []

    async def edit(**kw):
        drawings.append((clock.now, kw.get("embed")))
    view.message_ref = SimpleNamespace(edit=edit, id=1)

    await view._auto_refresh_loop()

    drawn = [(t, e) for t, e in drawings if e is not None]
    assert drawn, "no live update was drawn at all"
    late = [t for t, _ in drawn if t + timeout > TOKEN_LIFE - 30]
    assert not late, f"drawn at {late} s: the timeout's deletion no longer fits the token"
    last = drawn[-1][1]
    assert "remaining" not in (last.footer.text or ""), (
        f"the last drawing still announces more updates: {last.footer.text!r}")
    assert view.auto_refresh_enabled is False
    assert [str(item.emoji) for item in view.children][1] == "▶️"
