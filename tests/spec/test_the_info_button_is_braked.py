# -*- coding: utf-8 -*-
"""The status channel's info button is braked, and the WAN IP is asked once.

THE FINDING (spam audit, 2026-09-26, F4): the ℹ️ button in STATUS channels -
the public ones - had no spam brake at all, while its twin in the control
panel honoured the "info" cooldown. And every press, of either button, asked
three outside services (ipify, ifconfig.me, icanhazip) for the WAN IP afresh.
A few people clicking along made DDC hammer those services; a rate limit
there then emptied the "Public IP" line for everybody.

HOW THIS TEST CAN FAIL: it presses the status info button with the "info"
cooldown running (the press must be refused before any work), and it asks
for the WAN IP twice (one lookup must serve both). The first lookup must
still happen, and a press without a cooldown must still answer.

COUNTER-CHECK (2026-09-26): red before on the refused press and on the
second lookup.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import utils.common_helpers as helpers


# ---- the WAN IP ----------------------------------------------------------

class _Response:
    status = 200

    async def text(self):
        return "203.0.113.5"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def lookups(monkeypatch):
    import aiohttp

    made = []

    class _Session:
        def __init__(self, *args, **kwargs):
            made.append(1)

        def get(self, url):
            return _Response()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(aiohttp, "ClientSession", _Session)
    getattr(helpers, "_wan_ip_cache", {}).clear()
    yield made
    getattr(helpers, "_wan_ip_cache", {}).clear()


def test_the_wan_ip_is_asked_once(lookups):
    first = asyncio.run(helpers.get_wan_ip_async())
    second = asyncio.run(helpers.get_wan_ip_async())

    assert first == second == "203.0.113.5"
    assert len(lookups) == 1, f"{len(lookups)} lookups at outside services for one address"


# ---- the status info button ---------------------------------------------

def _spam(on_cooldown):
    service = MagicMock()
    service.is_enabled.return_value = True
    service.is_on_cooldown.return_value = on_cooldown
    service.get_remaining_cooldown.return_value = 4.0
    return service


def _press(monkeypatch, on_cooldown):
    from cogs.status_info_integration import StatusInfoButton

    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: _spam(on_cooldown))
    monkeypatch.setattr("cogs.status_info_integration.load_config",
                        lambda: {"channel_permissions": {}})
    button = StatusInfoButton.__new__(StatusInfoButton)
    button.container_name = "vrising"
    button.server_config = {"docker_name": "vrising"}
    button.info_config = {}
    button.cog = MagicMock()
    button._generate_info_embed = AsyncMock(return_value=MagicMock())
    interaction = MagicMock()
    interaction.user.id = 7
    interaction.channel_id = 1
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    asyncio.run(button.callback(interaction))
    return button, interaction


def test_a_press_on_cooldown_is_refused(monkeypatch):
    button, interaction = _press(monkeypatch, on_cooldown=True)

    assert button._generate_info_embed.await_count == 0, (
        "the info was built although the 'info' cooldown was running")
    assert interaction.response.send_message.await_count == 1, "the user was not told to wait"


def test_a_press_without_cooldown_still_answers(monkeypatch):
    button, interaction = _press(monkeypatch, on_cooldown=False)

    assert button._generate_info_embed.await_count == 1
    assert interaction.followup.send.await_count == 1
