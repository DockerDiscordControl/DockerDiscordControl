# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""Audit 2026-09, package B: cogs/control_ui.py fixes.

- B2: Admin/Info/Help buttons acknowledge the interaction first (defer) and reply via
      followup; an expired interaction (NotFound) is handled instead of raised.
- B10: MechDisplayButton re-checks the unlock state against the live mech level.
- B11: background Docker action task exceptions are logged and pending_actions is cleared.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs import control_ui
from cogs.control_ui import (AdminButton, HelpButton, InfoDropdownButton, MechDisplayButton,
                             _make_action_done_callback)


def _interaction(order=None):
    interaction = MagicMock()
    interaction.user.id = 42
    interaction.user.name = "tester"
    interaction.channel.id = 5

    async def _defer(*args, **kwargs):
        if order is not None:
            order.append("defer")

    interaction.response.defer = AsyncMock(side_effect=_defer)
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = True
    interaction.followup.send = AsyncMock()
    return interaction


def _not_found():
    return discord.NotFound(MagicMock(status=404, reason="Not Found"), "Unknown interaction")


def _spam_off():
    spam = MagicMock()
    spam.is_enabled.return_value = False
    return patch("services.infrastructure.spam_protection_service.get_spam_protection_service",
                 return_value=spam)


# ---------------------------------------------------------------------------
# B2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_button_defers_before_io_and_replies_via_followup():
    order = []
    interaction = _interaction(order)
    admin_service = MagicMock()
    admin_service.is_user_admin.return_value = True

    def _get_admin_service():
        order.append("admin_check")
        return admin_service

    scs = MagicMock()
    scs.get_all_servers.return_value = [
        {"docker_name": "web", "display_name": "Web", "order": 2},
        {"docker_name": "db", "display_name": "DB", "order": 1},
    ]
    button = AdminButton(MagicMock(), 5)
    with patch("services.admin.admin_service.get_admin_service", side_effect=_get_admin_service), \
         _spam_off(), patch("cogs.control_ui.get_server_config_service", return_value=scs):
        await button.callback(interaction)

    assert order[:2] == ["defer", "admin_check"]
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_awaited_once()
    kwargs = interaction.followup.send.await_args.kwargs
    assert kwargs["ephemeral"] is True
    assert isinstance(kwargs["view"], control_ui.AdminContainerSelectView)


@pytest.mark.asyncio
async def test_admin_button_expired_interaction_is_handled():
    interaction = _interaction()
    interaction.response.defer = AsyncMock(side_effect=_not_found())
    button = AdminButton(MagicMock(), 5)
    with patch("services.admin.admin_service.get_admin_service") as get_admin:
        await button.callback(interaction)  # must not raise
    get_admin.assert_not_called()
    interaction.followup.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_button_not_found_on_followup_is_caught():
    interaction = _interaction()
    interaction.followup.send = AsyncMock(side_effect=_not_found())
    admin_service = MagicMock()
    admin_service.is_user_admin.return_value = False
    button = AdminButton(MagicMock(), 5)
    with patch("services.admin.admin_service.get_admin_service", return_value=admin_service):
        await button.callback(interaction)  # NotFound must not escape


@pytest.mark.asyncio
async def test_admin_button_unauthorized_uses_followup():
    interaction = _interaction()
    admin_service = MagicMock()
    admin_service.is_user_admin.return_value = False
    button = AdminButton(MagicMock(), 5)
    with patch("services.admin.admin_service.get_admin_service", return_value=admin_service):
        await button.callback(interaction)
    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_awaited_once()
    assert "not authorized" in interaction.followup.send.await_args.args[0]


@pytest.mark.asyncio
async def test_info_button_defers_first():
    interaction = _interaction()
    scs = MagicMock()
    scs.get_all_servers.return_value = [{"docker_name": "web", "info": {"enabled": False}}]
    button = InfoDropdownButton(MagicMock(), 5)
    with _spam_off(), patch("cogs.control_ui.get_server_config_service", return_value=scs):
        await button.callback(interaction)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.response.send_message.assert_not_awaited()
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_info_button_expired_interaction_is_handled():
    interaction = _interaction()
    interaction.response.defer = AsyncMock(side_effect=_not_found())
    button = InfoDropdownButton(MagicMock(), 5)
    await button.callback(interaction)
    interaction.followup.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_help_button_defers_first_and_sends_embed():
    interaction = _interaction()
    button = HelpButton(MagicMock(), 5)
    with _spam_off():
        await button.callback(interaction)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    interaction.response.send_message.assert_not_awaited()
    kwargs = interaction.followup.send.await_args.kwargs
    assert isinstance(kwargs["embed"], discord.Embed)
    assert kwargs["ephemeral"] is True


# ---------------------------------------------------------------------------
# B10: MechDisplayButton live unlock check
# ---------------------------------------------------------------------------

def _mech_service(level=None, exc=None):
    service = MagicMock()
    if exc is not None:
        service.get_mech_state_service.side_effect = exc
    else:
        service.get_mech_state_service.return_value = SimpleNamespace(success=True, level=level)
    return patch("services.mech.mech_service.get_mech_service", return_value=service)


@pytest.mark.parametrize("level,registered_unlocked,current_level,expected", [
    (5, True, 3, False),   # persistent registration said unlocked, but level 5 is locked
    (4, False, 3, False),  # real "Next" button stays locked
    (2, False, 3, True),   # unlocked level registered as locked -> live check unlocks
    (3, True, 3, True),
])
@pytest.mark.asyncio
async def test_mech_display_button_uses_live_level(level, registered_unlocked, current_level, expected):
    button = MechDisplayButton(MagicMock(), level, "Next", unlocked=registered_unlocked)
    with _mech_service(level=current_level):
        assert button._is_unlocked_now() is expected


@pytest.mark.asyncio
async def test_mech_display_button_falls_back_to_flag_on_error():
    button = MechDisplayButton(MagicMock(), 7, "Next", unlocked=False)
    with _mech_service(exc=RuntimeError("down")):
        assert button._is_unlocked_now() is False


# ---------------------------------------------------------------------------
# B11: done-callback logs exceptions and clears pending_actions
# ---------------------------------------------------------------------------

async def _run_task_with_callback(coro, cog, entry):
    task = asyncio.create_task(coro)
    task.add_done_callback(_make_action_done_callback(cog, "web", entry, "docker stop for web"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return task


@pytest.mark.asyncio
async def test_action_task_exception_is_logged_and_pending_cleared():
    entry = {"action": "stop"}
    cog = SimpleNamespace(pending_actions={"web": entry})

    async def boom():
        raise AttributeError("docker exploded")

    with patch.object(control_ui, "logger") as log:
        await _run_task_with_callback(boom(), cog, entry)
    assert "web" not in cog.pending_actions
    log.error.assert_called_once()
    assert "docker exploded" in log.error.call_args.args[0]


@pytest.mark.asyncio
async def test_action_task_does_not_clear_newer_pending_entry():
    old_entry, new_entry = {"action": "stop"}, {"action": "start"}
    cog = SimpleNamespace(pending_actions={"web": new_entry})

    async def boom():
        raise RuntimeError("fail")

    with patch.object(control_ui, "logger"):
        await _run_task_with_callback(boom(), cog, old_entry)
    assert cog.pending_actions["web"] is new_entry


@pytest.mark.asyncio
async def test_action_task_success_logs_nothing():
    entry = {"action": "stop"}
    cog = SimpleNamespace(pending_actions={})

    async def ok():
        return True

    with patch.object(control_ui, "logger") as log:
        await _run_task_with_callback(ok(), cog, entry)
    log.error.assert_not_called()
