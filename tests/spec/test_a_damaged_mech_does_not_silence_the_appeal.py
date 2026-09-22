# -*- coding: utf-8 -*-
"""A mech that cannot be healed must not swallow the donation appeal.

THE FINDING (review E12, the DDC-exception scan): the monthly donation task
grants the mech $1.00 when its power has run to zero, and the handler around
that grant carries the comment "Continue anyway to send the message". That
intent is exactly right - the appeal has nothing to do with whether the gift
worked - but the handler lists ``(ValueError, TypeError, RuntimeError)``.

``add_system_donation`` calls ``_heal_if_lagging`` under the lock, and review
D1 gave that helper a ``raise``: a snapshot that lags behind the event log
and cannot be rebuilt now raises ``MechStateError`` instead of quietly burying
a donation. That repair was right, and it is the second place it reaches past
a handler that predates it - the first was the startup power gift (review E8).

``MechStateError -> MechServiceError -> DDCBaseException -> Exception`` is in
none of the three tuples in this file: not the inner one, and not either of
the two around the whole task. So the exception left the task entirely, and
the month's appeal was sent to nobody - for a reason that had nothing to do
with the appeal.

This is the same sentence as E8, and the reason it is worth its own test: the
inner handler ALREADY says what should happen. Only the type list disagreed.
"""

import pytest

from services.exceptions import MechStateError
from services.scheduling import donation_message_service


class _Channel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.sent = []

    async def send(self, **kwargs):
        self.sent.append(kwargs)


class _Bot:
    def __init__(self, channels):
        self._channels = {channel.id: channel for channel in channels}

    def get_channel(self, channel_id):
        return self._channels.get(channel_id)


class _State:
    level = 3
    power_current = 0.0      # zero, so the gift branch runs
    evo_percent = 40


@pytest.fixture
def world(monkeypatch):
    """One status channel, and a mech whose healing raises."""
    import services.config.config_service as config_service
    monkeypatch.setattr(config_service, "load_config", lambda: {
        "channel_permissions": {
            "111": {"name": "status", "commands": {"serverstatus": True}},
        }
    })

    class _Progress:
        @staticmethod
        def get_state():
            return _State()

        @staticmethod
        def add_system_donation(**kwargs):
            raise MechStateError("snapshot lags behind the event log")

    import services.mech.progress_service as progress_service
    monkeypatch.setattr(progress_service, "get_progress_service", lambda: _Progress())

    channel = _Channel(111)
    return _Bot([channel]), channel


@pytest.mark.asyncio
async def test_the_appeal_is_still_sent(world):
    bot, channel = world

    await donation_message_service.execute_donation_message_task(bot=bot)

    assert channel.sent, (
        "a mech whose healing raised took the whole donation appeal with it - "
        "the handler's own comment says 'Continue anyway to send the message'"
    )


@pytest.mark.asyncio
async def test_the_task_does_not_raise_at_its_caller(world):
    """The scheduler calls this. It must get an answer, not an exception."""
    bot, _channel = world

    result = await donation_message_service.execute_donation_message_task(bot=bot)

    assert result is True


@pytest.mark.asyncio
async def test_the_failed_gift_is_not_claimed_as_given(world):
    """The $1.00 was NOT granted, so the message must not announce it."""
    bot, channel = world

    await donation_message_service.execute_donation_message_task(bot=bot)

    embeds = [kwargs.get("embed") for kwargs in channel.sent]
    titles = [getattr(embed, "title", "") or "" for embed in embeds]
    assert not any("Motor Maintenance" in title for title in titles), (
        f"the appeal announced a $1.00 gift that never happened: {titles}"
    )
