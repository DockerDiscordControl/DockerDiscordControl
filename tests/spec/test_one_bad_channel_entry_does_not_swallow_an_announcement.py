# -*- coding: utf-8 -*-
"""One unusable channel entry does not cost the whole announcement.

THE FINDING (independent review of the donation path, 2026-09-23): the loop
that announces a web donation walks channel_permissions and guards each channel
with

    except (discord.errors.DiscordException, RuntimeError)

Two ordinary kinds of bad entry are in neither type. A key that is not a number
makes ``int(channel_id_str)`` raise ValueError; an entry that is not a dict
makes ``channel_info.get(...)`` raise AttributeError. Neither is caught beside
the channel, so:

* the ValueError lands in the embed-level handler and ABANDONS the remaining
  channels;
* the AttributeError reaches the loop boundary and abandons the rest of the
  whole 20-announcement batch as well.

And the notification file was unlinked before any of this - that is deliberate,
so a crash cannot announce the same donation twice - so a donation somebody
really paid is gone for good, and the channels after the bad entry got nothing.
The operator sees one error line.

The parallel path knows this already: donation_message_service.py checks
``isinstance(channel_info, dict)`` before touching an entry (review C74). The
web-announcement loop never got the same guard.

HOW THIS TEST CAN FAIL: it puts a bad entry in front of a good one and asks
whether the good channel got its embed. If it did not, the test is red.

COUNTER-CHECK (2026-09-23): red before - the good channel was never reached,
for both kinds of bad entry. The last test keeps the ordinary case: a channel
that is simply switched off is still skipped without an error.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import tasks

import cogs.docker_control as dc

NOTIFICATION = {"type": "donation", "donor": "Alex", "amount": 5}


@pytest.fixture
def world(monkeypatch):
    """The loop body, with one real-looking donation waiting."""
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
    good = MagicMock()
    good.name = "announcements"
    good.send = AsyncMock()
    bot.get_channel.side_effect = lambda cid: good if cid == 222 else None

    dc.setup(bot)
    cog = dc.DockerControlCog.return_value
    return bot, good, cog.donation_notification_task.coro


def _errors(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("bad_entry", [
    pytest.param({"not-a-number": {"donation_broadcasts": True}}, id="key-is-not-a-number"),
    pytest.param({"111": None}, id="entry-is-not-a-dict"),
    pytest.param({"111": "yes"}, id="entry-is-a-string"),
])
def test_the_good_channel_still_gets_the_announcement(world, monkeypatch, caplog, bad_entry):
    """THE FINDING: a donation that was paid for was lost for good."""
    _bot, good, body = world
    channels = dict(bad_entry)
    channels["222"] = {"donation_broadcasts": True}
    monkeypatch.setattr(dc, "load_config", lambda: {"channel_permissions": channels})

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    assert good.send.await_count == 1, (
        "the bad entry cost the announcement: the channel behind it got nothing, "
        "and the notification file was already deleted")


def test_the_bad_entry_is_not_passed_over_in_silence(world, monkeypatch, caplog):
    """It is the operator's configuration - they have to hear about it."""
    _bot, _good, body = world
    monkeypatch.setattr(dc, "load_config", lambda: {
        "channel_permissions": {"111": None, "222": {"donation_broadcasts": True}}})

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    assert _errors(caplog), "an unusable channel entry left no error in the log"


def test_a_channel_with_broadcasts_off_is_still_just_skipped(world, monkeypatch, caplog):
    """Counter-check: the everyday case is not an error."""
    _bot, good, body = world
    monkeypatch.setattr(dc, "load_config", lambda: {
        "channel_permissions": {"222": {"donation_broadcasts": False}}})

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    assert good.send.await_count == 0
    assert _errors(caplog) == [], "switching broadcasts off was treated as an error"
