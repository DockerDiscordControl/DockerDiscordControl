# -*- coding: utf-8 -*-
"""The donation appeal goes where the docstring says it goes.

THE FINDING (review C74, section 25 F1): the scheduled donation message
walks ``config['channel_permissions']`` and sends its embed to every channel
id in that map, with no look at what the channel is for. A channel
configured only for ``control`` - the one where the operator's start/stop
buttons live - or only for ``download`` receives the public donation appeal
all the same. The code's own comment says "Send message to all status
channels".

``services/member_count/service.py`` asks the question properly for the
conceptually identical loop: a status channel is one whose
``commands.serverstatus`` is true. The appeal asks the same question now.
"""

import pytest

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


def _permissions(**kinds):
    """channel id -> what that channel is allowed to do."""
    return {str(channel_id): {"name": name, "commands": {kind: True}}
            for channel_id, (name, kind) in kinds.items()}


@pytest.fixture
def world(monkeypatch):
    """A guild with one status channel, one control channel, one download one."""
    permissions = {
        "111": {"name": "status", "commands": {"serverstatus": True, "control": False}},
        "222": {"name": "control", "commands": {"serverstatus": False, "control": True}},
        "333": {"name": "downloads", "commands": {"download": True}},
    }
    # Both are imported inside the function body, so they are patched at
    # their source.
    import services.config.config_service as config_service
    monkeypatch.setattr(config_service, "load_config",
                        lambda: {"channel_permissions": permissions})

    class _State:
        level = 3
        power_current = 5.0
        evo_percent = 40

    class _Progress:
        @staticmethod
        def get_state():
            return _State()

    import services.mech.progress_service as progress_service
    monkeypatch.setattr(progress_service, "get_progress_service", lambda: _Progress())
    channels = [_Channel(111), _Channel(222), _Channel(333)]
    return _Bot(channels), {channel.id: channel for channel in channels}


@pytest.mark.asyncio
async def test_a_control_channel_gets_no_appeal(world):
    bot, channels = world

    await donation_message_service.execute_donation_message_task(bot=bot)

    assert channels[222].sent == [], (
        "the start/stop channel was sent a public donation appeal"
    )


@pytest.mark.asyncio
async def test_a_download_channel_gets_no_appeal(world):
    bot, channels = world

    await donation_message_service.execute_donation_message_task(bot=bot)

    assert channels[333].sent == []


@pytest.mark.asyncio
async def test_the_status_channel_still_gets_it(world):
    """Counter-check: sending nowhere would pass the two tests above."""
    bot, channels = world

    await donation_message_service.execute_donation_message_task(bot=bot)

    assert len(channels[111].sent) == 1


@pytest.mark.asyncio
async def test_a_channel_config_of_the_wrong_shape_is_skipped(world, monkeypatch):
    """Counter-check: a broken entry costs that entry, not the whole run."""
    bot, channels = world
    import services.config.config_service as config_service
    # The broken entry comes FIRST: with it second, a crash on it would leave
    # the good channel already served and the test could not tell "skipped"
    # from "died here" (found by mutation M3 of review C74).
    monkeypatch.setattr(config_service, "load_config", lambda: {
        "channel_permissions": {
            "222": "not a mapping at all",
            "111": {"name": "status", "commands": {"serverstatus": True}},
        }})

    result = await donation_message_service.execute_donation_message_task(bot=bot)

    assert result is True, "one broken entry ended the whole appeal"
    assert len(channels[111].sent) == 1
    assert channels[222].sent == []
