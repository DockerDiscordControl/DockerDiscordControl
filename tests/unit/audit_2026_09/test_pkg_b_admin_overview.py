# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""Audit 2026-09, package B: cogs/admin_overview.py fixes.

- B3: Stop All / Restart All respect per-container allowed_actions, report the skipped
      containers, and treat a missing 'active' field as active.
- B8: the post-bulk-action refresh finds the Admin Overview by its tracked message id
      (the embed title is translated, so title matching failed in German).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs import admin_overview
from cogs.admin_overview import (ConfirmRestartAllButton, ConfirmStopAllButton,
                                 _refresh_tracked_admin_overview)
from cogs.translation_manager import _
from services.docker_status.models import ContainerStatusResult

SERVERS = [
    {"docker_name": "allowed", "allowed_actions": ["status", "start", "stop", "restart"], "active": True},
    {"docker_name": "status_only", "allowed_actions": ["status"], "active": True},
    {"docker_name": "no_active_field", "allowed_actions": ["stop", "restart"]},
    {"docker_name": "inactive", "allowed_actions": ["stop", "restart"], "active": False},
]


def _running_cache():
    cache = MagicMock()
    cache.get.side_effect = lambda name: {"data": ContainerStatusResult.success_result(
        docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1MB",
        uptime="1m", details_allowed=True)}
    return cache


async def _run_bulk(button_cls, action):
    cog = MagicMock()
    cog._bulk_operation_in_progress = False
    button = button_cls(cog, 1)
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    scs = MagicMock()
    scs.get_all_servers.return_value = [dict(s) for s in SERVERS]
    action_mock = AsyncMock(return_value=True)

    with patch.object(admin_overview, "get_server_config_service", return_value=scs), \
         patch.object(admin_overview, "get_status_cache_service", return_value=_running_cache()), \
         patch("services.docker_service.docker_action_service.docker_action_service_first", action_mock), \
         patch.object(button_cls, "_delayed_overview_update", new=AsyncMock()), \
         patch("asyncio.sleep", new=AsyncMock()):
        await button.callback(interaction)

    acted = [c.args for c in action_mock.await_args_list]
    embed = interaction.followup.send.await_args.kwargs["embed"]
    return acted, embed


@pytest.mark.parametrize("button_cls,action", [
    (ConfirmStopAllButton, "stop"),
    (ConfirmRestartAllButton, "restart"),
])
@pytest.mark.asyncio
async def test_bulk_action_respects_allowed_actions_and_active_default(button_cls, action):
    acted, embed = await _run_bulk(button_cls, action)

    # status_only is skipped (not allowed), inactive is filtered, missing 'active' means active
    assert acted == [("allowed", action), ("no_active_field", action)]
    expected = _("\nSkipped (action not allowed): **{count}** containers").format(count=1)
    assert expected.strip() in embed.description


# ---------------------------------------------------------------------------
# B8
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_uses_tracked_admin_overview_id():
    cog = MagicMock()
    cog.channel_server_message_ids = {1: {"admin_overview": 555, "overview": 444}}
    cog._update_overview_message = AsyncMock(return_value=True)

    assert await _refresh_tracked_admin_overview(cog, 1) is True
    cog._update_overview_message.assert_awaited_once_with(1, 555, "admin_overview")


@pytest.mark.asyncio
async def test_refresh_without_tracked_message_is_noop():
    cog = MagicMock()
    cog.channel_server_message_ids = {1: {"overview": 444}}
    cog._update_overview_message = AsyncMock()

    assert await _refresh_tracked_admin_overview(cog, 1) is False
    cog._update_overview_message.assert_not_awaited()


@pytest.mark.parametrize("button_cls", [ConfirmStopAllButton, ConfirmRestartAllButton])
@pytest.mark.asyncio
async def test_update_admin_overview_no_title_matching(button_cls):
    cog = MagicMock()
    cog.channel_server_message_ids = {1: {"admin_overview": 555}}
    cog._update_overview_message = AsyncMock(return_value=True)
    button = button_cls(cog, 1)

    await button._update_admin_overview()

    cog._update_overview_message.assert_awaited_once_with(1, 555, "admin_overview")
    cog.bot.get_channel.assert_not_called()  # no channel-history scan by title anymore
