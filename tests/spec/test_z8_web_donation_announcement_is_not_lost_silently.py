# -*- coding: utf-8 -*-
# @covers Z8
"""Z8 - a web-panel donation announcement is never lost silently.

The loop ``check_donation_notifications`` (cogs/docker_control.py, inside
``setup``) picks up the notification the web panel leaves for the bot and
announces the donation in the channels. Picking it up DELETES the file
(notification_service.check_and_retrieve_notification) - from then on the
announcement exists nowhere but in this call.

THE FINDING (2026-09-19, Z8 sweep): two ways to lose it without a trace.

1. An AttributeError after the pick-up (e.g. a channel entry of an
   unexpected shape) passes both inner handlers and reaches the outer one,
   which logged it at DEBUG - Z8's own definition of "broken": the error
   ends up only in the debug log.
2. Any other exception type (TypeError, KeyError, ...) is caught nowhere and
   leaves the loop body. A ``tasks.loop`` whose body raises stops for good:
   from then on NO web donation is announced until the bot restarts, and the
   only trace is the one traceback of the moment it died.

HOW IT IS CHECKED: ``setup`` runs with the cog and the config service
replaced and ``Loop.start`` disabled; the test then calls the loop's body
itself. The notification service hands out a real-looking donation - the
file is "gone" from that moment, as in operation.
"""

import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from discord.ext import tasks

import cogs.docker_control as dc

NOTIFICATION = {"type": "donation", "donor": "Alex", "amount": 5}


@pytest.fixture
def loop_body(monkeypatch):
    monkeypatch.setattr(tasks.Loop, "start", lambda self, *a, **k: None)
    monkeypatch.setattr(dc, "DockerControlCog", MagicMock())
    config_service = MagicMock()
    config_service.get_config.return_value = {}
    monkeypatch.setattr("services.config.config_service.get_config_service",
                        lambda: config_service)
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled",
                        lambda: False)
    notifications = MagicMock()
    notifications.check_and_retrieve_notification.return_value = dict(NOTIFICATION)
    monkeypatch.setattr(
        "services.donation.notification_service.get_donation_notification_service",
        lambda: notifications)
    bot = MagicMock()
    dc.setup(bot)
    cog = dc.DockerControlCog.return_value
    return bot, cog.donation_notification_task.coro


def _errors(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_an_unexpected_channel_entry_is_logged_as_an_error(loop_body, monkeypatch, caplog):
    """Case 1: AttributeError after the pick-up - was DEBUG only."""
    _bot, body = loop_body
    monkeypatch.setattr(dc, "load_config", lambda: {"channel_permissions": {"123": None}})

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    assert _errors(caplog), (
        "The donation announcement was lost after its file had been deleted, "
        "and the only trace is a DEBUG line - Z8 counts that as silent."
    )


def test_any_other_error_does_not_stop_the_loop(loop_body, monkeypatch, caplog):
    """Case 2: TypeError - left the loop body, which stops a tasks.loop for good."""
    bot, body = loop_body
    monkeypatch.setattr(dc, "load_config", lambda: {"channel_permissions": {"123": {}}})
    bot.get_channel.side_effect = TypeError("unexpected")

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())      # must not raise

    assert _errors(caplog), "the lost announcement left no error in the log"
