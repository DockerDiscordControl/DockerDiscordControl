# -*- coding: utf-8 -*-
"""An announcement that reached no channel is an error, not an info line.

THE FINDING (independent review of the donation path, 2026-09-23): the bot
takes a waiting donation announcement with check_and_retrieve_notification,
which reads the file and UNLINKS it at once - deliberately, so a crash cannot
announce the same donation twice. Delivery is attempted after that.

If every channel is missed - the gateway is reconnecting and the channel cache
is cold, the configured channels were deleted in Discord, the bot was removed
from the server - the only trace was

    logger.info("🔔 Processed Web UI donation: Bob $50 - sent to 0 channels")

INFO, and phrased as a success. Meanwhile the panel had already answered
published_to_discord: true, which only ever meant "the file was written".

So: a donor paid, the operator saw a green confirmation, nobody in Discord
heard anything, and the announcement is gone from disk. SPEC.md Z8: no error
is silent.

A channel that is simply switched off for donation broadcasts is NOT this
case - nothing went wrong there, and it must not become a recurring error in
the log.

HOW THIS TEST CAN FAIL: it lets every channel miss and reads the log. No error
is red.

COUNTER-CHECK (2026-09-23): red before - one INFO line saying "sent to 0
channels". The last two tests keep it from crying wolf: a delivery that
worked, and channels deliberately switched off, are both silent.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import tasks

import cogs.docker_control as dc

NOTIFICATION = {"type": "donation", "donor": "Bob", "amount": 50}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(tasks.Loop, "start", lambda self, *a, **k: None)
    monkeypatch.setattr(dc, "DockerControlCog", MagicMock())
    config_service = MagicMock()
    config_service.get_config.return_value = {}
    monkeypatch.setattr("services.config.config_service.get_config_service",
                        lambda: config_service)
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled",
                        lambda: False)
    notifications = MagicMock()
    notifications.check_and_retrieve_notification.side_effect = [dict(NOTIFICATION), None]
    monkeypatch.setattr(
        "services.donation.notification_service.get_donation_notification_service",
        lambda: notifications)

    bot = MagicMock()
    dc.setup(bot)
    cog = dc.DockerControlCog.return_value
    return bot, cog.donation_notification_task.coro


def _errors(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_reaching_no_channel_at_all_is_an_error(world, monkeypatch, caplog):
    """THE FINDING: a paid-for thank-you vanished behind an info line."""
    bot, body = world
    bot.get_channel.return_value = None
    monkeypatch.setattr(dc, "load_config", lambda: {"channel_permissions": {
        "222": {"donation_broadcasts": True}, "333": {"donation_broadcasts": True}}})

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    assert _errors(caplog), (
        "the announcement reached nobody, its file was already deleted, and "
        "the only trace was an INFO line that reads like a success")


def test_a_delivery_that_worked_stays_quiet(world, monkeypatch, caplog):
    """Counter-check: the everyday case must not become an error."""
    bot, body = world
    channel = MagicMock()
    channel.name = "announcements"
    channel.send = AsyncMock()
    bot.get_channel.return_value = channel
    monkeypatch.setattr(dc, "load_config", lambda: {"channel_permissions": {
        "222": {"donation_broadcasts": True}}})

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    assert channel.send.await_count == 1
    assert _errors(caplog) == [], _errors(caplog)


def test_channels_switched_off_on_purpose_stay_quiet(world, monkeypatch, caplog):
    """Counter-check: the operator turned broadcasts off. Nothing is wrong."""
    bot, body = world
    channel = MagicMock()
    channel.send = AsyncMock()
    bot.get_channel.return_value = channel
    monkeypatch.setattr(dc, "load_config", lambda: {"channel_permissions": {
        "222": {"donation_broadcasts": False}, "333": {"donation_broadcasts": False}}})

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    assert channel.send.await_count == 0
    assert _errors(caplog) == [], (
        f"switching broadcasts off was turned into a recurring error: {_errors(caplog)}")


def test_no_channels_configured_at_all_stays_quiet(world, monkeypatch, caplog):
    """Counter-check: an installation with no channels yet."""
    _bot, body = world
    monkeypatch.setattr(dc, "load_config", lambda: {"channel_permissions": {}})

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    assert _errors(caplog) == [], _errors(caplog)
