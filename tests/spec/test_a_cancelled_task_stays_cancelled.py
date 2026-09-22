# -*- coding: utf-8 -*-
"""Cancelling a status task really cancels it.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 08 F4, re-checked 2026-09-20):
three handlers in ``status_handlers.py`` list ``asyncio.CancelledError``
among the exceptions they catch and then simply log it -
``bulk_update_status_cache``, ``send_server_status`` and
``_edit_single_message``. A cancellation is not an error: it is how asyncio
tells a coroutine to stop. Swallowed, the task reports itself finished
although it was told to stop - on shutdown the bot waits for work that has
already been asked to end, and a caller's ``wait_for`` timeout no longer
stops what it timed out on.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_handlers import StatusHandlersMixin

NAME = "vrising"
SERVER = {"docker_name": NAME, "name": "V-Rising", "allow_detailed_status": True}


class _Cache:
    def __init__(self):
        self.entries = {}

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, data, timestamp=None):
        self.entries[name] = data

    def set_error(self, name, error):
        self.entries[name] = error


def _mixin():
    mixin = StatusHandlersMixin()
    mixin.bot = MagicMock()
    mixin.status_cache_service = _Cache()
    mixin.cache_ttl_seconds = 300
    mixin.last_message_update_time = {}
    mixin.channel_server_message_ids = {}
    mixin.pending_actions = {}
    mixin.expanded_states = {}
    return mixin


def _connectivity():
    """Docker answers "I am here" - these paths check that before anything else."""
    service = MagicMock()
    service.check_connectivity = AsyncMock(
        return_value=MagicMock(is_connected=True, error_message=None))
    return service


def _servers():
    service = MagicMock()
    service.get_all_servers.return_value = [SERVER]
    service.get_server_by_docker_name.return_value = SERVER
    return service


@pytest.mark.asyncio
async def test_a_cancelled_bulk_update_is_not_reported_as_done():
    mixin = _mixin()
    mixin.bulk_fetch_container_status = AsyncMock(side_effect=asyncio.CancelledError())

    with patch("cogs.status_handlers.get_server_config_service", return_value=_servers()):
        with pytest.raises(asyncio.CancelledError):
            await mixin.bulk_update_status_cache([NAME])


@pytest.mark.asyncio
async def test_a_real_error_in_the_bulk_update_is_still_caught():
    """Counter-check: an ordinary failure must not escape and kill the loop."""
    mixin = _mixin()
    mixin.bulk_fetch_container_status = AsyncMock(side_effect=RuntimeError("docker is away"))

    with patch("cogs.status_handlers.get_server_config_service", return_value=_servers()):
        await mixin.bulk_update_status_cache([NAME])  # must not raise


@pytest.mark.asyncio
async def test_a_cancelled_status_send_is_not_reported_as_done():
    mixin = _mixin()
    # Both, because the send path asks for the status before it builds anything.
    mixin.get_status = AsyncMock(side_effect=asyncio.CancelledError())
    mixin._generate_status_embed_and_view = AsyncMock(side_effect=asyncio.CancelledError())
    channel = SimpleNamespace(id=42, name="status")

    with patch("services.infrastructure.docker_connectivity_service."
               "get_docker_connectivity_service", return_value=_connectivity()), \
         patch("cogs.status_handlers.get_server_config_service", return_value=_servers()):
        with pytest.raises(asyncio.CancelledError):
            await mixin.send_server_status(channel, SERVER, {}, allow_toggle=True)


@pytest.mark.asyncio
async def test_a_cancelled_message_edit_is_not_reported_as_done():
    mixin = _mixin()
    mixin.get_status = AsyncMock(side_effect=asyncio.CancelledError())
    mixin._generate_status_embed_and_view = AsyncMock(side_effect=asyncio.CancelledError())
    mixin.bot.get_channel = MagicMock(return_value=SimpleNamespace(id=42, name="status"))

    with patch("services.infrastructure.docker_connectivity_service."
               "get_docker_connectivity_service", return_value=_connectivity()), \
         patch("cogs.status_handlers.get_server_config_service", return_value=_servers()):
        with pytest.raises(asyncio.CancelledError):
            await mixin._edit_single_message(42, "V-Rising", 7, {})
