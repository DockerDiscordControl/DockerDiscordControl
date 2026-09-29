# -*- coding: utf-8 -*-
"""A control channel added after a version's first start still gets its notice.

THE FINDING (stage 4 review before v3.1.0, section 20 pass 3 F4): if a new
version first started with no control channel configured, its "DDC has been
updated" notice was marked as shown - "to avoid repeated attempts" - and a
control channel added afterwards never got it.

THE OPERATOR (2026-09-29): the channel added later still gets the running
version's notice.

THE CONTRACT: with no control channel nothing is marked; the notice goes out
at the next start that finds one. A channel that already has it is not told
twice.

HOW THIS TEST CAN FAIL: a start without control channels marks the version
done again; or the channel that got it once gets it again.

COUNTER-CHECK (2026-09-29): the first case red before the change, the
second green before and after.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.infrastructure.update_notifier as un


@pytest.fixture
def notifier(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_VERSION", "3.1.0")
    monkeypatch.setattr(un, "fetch_release_notes", AsyncMock(return_value=None))
    return un.UpdateNotifier(config_dir=str(tmp_path))


def _with_channels(monkeypatch, ids):
    monkeypatch.setattr(un, "load_config", lambda: {})
    monkeypatch.setattr("services.config.channel_roles.control_channel_ids", lambda config: list(ids))


def _bot():
    channel = MagicMock()
    channel.send = AsyncMock()
    bot = MagicMock()
    bot.get_channel.return_value = channel
    return bot, channel


def test_a_channel_added_after_the_first_start_gets_the_notice(notifier, monkeypatch):
    _with_channels(monkeypatch, [])
    bot, channel = _bot()
    asyncio.run(notifier.send_update_notification(bot))

    _with_channels(monkeypatch, [4242])
    asyncio.run(notifier.send_update_notification(bot))
    assert channel.send.await_count == 1, "the control channel added later never got the notice"


def test_a_channel_that_has_it_is_not_told_twice(notifier, monkeypatch):
    _with_channels(monkeypatch, [4242])
    bot, channel = _bot()
    asyncio.run(notifier.send_update_notification(bot))
    asyncio.run(notifier.send_update_notification(bot))
    assert channel.send.await_count == 1
