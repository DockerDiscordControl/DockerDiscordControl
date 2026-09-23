# -*- coding: utf-8 -*-
"""A monthly donation appeal that reached nobody is not reported as sent.

THE FINDING (independent review of the donation path, 2026-09-23):
execute_donation_message_task ends in a plain ``return True`` whatever
happened on the way. Three paths reach it having told nobody:

* the bot instance is None - a warning in the log, then True;
* every bot.get_channel() comes back None, for instance while the gateway is
  reconnecting and the channel cache is cold - sent 0, failed N, then True;
* no channel is configured for the status overview at all - sent 0, failed 0.

The scheduler believes that answer: it writes last_run_success = True and a
"DONATION_MESSAGE ... Result: Success" line into the action log. The task list
then shows a green badge for an appeal nobody received - and this is a MONTHLY
task, so there is no retry for a month.

The third case is the operator's own configuration and stays a success; it is
not a failure that nobody set up a status channel. But it must not be silent
either, so it is said plainly instead of hidden in a debug line.

HOW THIS TEST CAN FAIL: it runs the task with no reachable channel and reads
the answer. True means red.

COUNTER-CHECK (2026-09-23): red before - True for all three. The last two tests
keep the everyday case: an appeal that did go out is still a success, and one
channel failing out of two is not turned into a failure.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.scheduling.donation_message_service as dms


class _State:
    level = 3
    power_current = 12.5
    evo_percent = 40
    power_max = 100.0


@pytest.fixture
def world(monkeypatch):
    """A mech with power, so the ordinary appeal branch is taken.

    execute_donation_message_task imports both of these INSIDE the function, so
    the source modules are what has to be patched - patching the names on
    donation_message_service would do nothing at all.
    """
    import services.config.config_service as config_service
    import services.mech.progress_service as progress_service

    service = MagicMock()
    service.get_state.return_value = _State()
    monkeypatch.setattr(progress_service, "get_progress_service", lambda *a, **k: service)
    monkeypatch.setattr(config_service, "load_config", lambda *a, **k: {"channel_permissions": {}})
    return config_service


def _status_channel():
    return {"commands": {"serverstatus": True}}


def _run(bot):
    return asyncio.run(dms.execute_donation_message_task(bot=bot))


def test_without_a_bot_the_task_does_not_claim_success(world, monkeypatch):
    """THE FINDING: the panel showed a green badge for nothing at all."""
    monkeypatch.setattr(world, "load_config", lambda *a, **k: {"channel_permissions": {
        "222": _status_channel()}})

    assert _run(None) is False, (
        "the task reported success although there was no bot to send with")


def test_when_no_channel_can_be_reached_the_task_does_not_claim_success(world, monkeypatch):
    """The gateway is reconnecting and the channel cache is cold."""
    monkeypatch.setattr(world, "load_config", lambda *a, **k: {"channel_permissions": {
        "222": _status_channel(), "333": _status_channel()}})
    bot = MagicMock()
    bot.get_channel.return_value = None

    assert _run(bot) is False, (
        "sent to 0 channels, failed 2 - and the task called itself successful")


def test_no_status_channel_is_a_success_but_not_a_silence(world, monkeypatch, caplog):
    """The operator configured none. That is their choice, not a failure."""
    monkeypatch.setattr(world, "load_config", lambda *a, **k: {"channel_permissions": {
        "222": {"commands": {"control": True}}}})
    bot = MagicMock()

    with caplog.at_level(logging.DEBUG):
        assert _run(bot) is True

    said = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("status channel" in m.lower() or "no channel" in m.lower() for m in said), (
        f"nobody was told the appeal went nowhere: {said}")


def test_an_appeal_that_went_out_is_still_a_success(world, monkeypatch):
    """Counter-check: the everyday case is unchanged."""
    monkeypatch.setattr(world, "load_config", lambda *a, **k: {"channel_permissions": {
        "222": _status_channel()}})
    channel = MagicMock()
    channel.send = AsyncMock()
    bot = MagicMock()
    bot.get_channel.return_value = channel

    assert _run(bot) is True
    assert channel.send.await_count == 1


def test_one_channel_out_of_two_failing_is_not_a_failed_task(world, monkeypatch):
    """Counter-check: reaching somebody is reaching somebody."""
    monkeypatch.setattr(world, "load_config", lambda *a, **k: {"channel_permissions": {
        "222": _status_channel(), "333": _status_channel()}})
    channel = MagicMock()
    channel.send = AsyncMock()
    bot = MagicMock()
    bot.get_channel.side_effect = lambda cid: channel if cid == 222 else None

    assert _run(bot) is True
    assert channel.send.await_count == 1
