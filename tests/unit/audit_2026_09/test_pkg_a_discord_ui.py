# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Audit 2026-09 package A regression tests       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Regression tests for the Discord task UI (audit 2026-09 A8, A9, A10)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cogs.status_info_integration as sii
from services.scheduling.schedule_helpers import ScheduleValidationError
from services.scheduling.scheduler import ScheduledTask


CHANNEL = 555_000_111


def _interaction():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    # Since 2026-09-20 creating a task needs the channel's 'schedule' permission
    # (review B3), so the fake interaction carries a real channel id and user id.
    interaction.channel_id = CHANNEL
    interaction.user = SimpleNamespace(id=4711, name="tester", __str__=lambda self: "tester")
    return interaction


def _config(**extra):
    """Config for these tests: the channel may schedule (review B3)."""
    config = {"channel_permissions": {str(CHANNEL): {"commands": {"schedule": True}}}}
    config.update(extra)
    return config


def _ready_view(monkeypatch, allowed, action="restart"):
    monkeypatch.setattr(sii, "_get_allowed_task_actions", lambda name: list(allowed))
    monkeypatch.setattr(sii, "load_config", lambda: _config())
    monkeypatch.setattr("cogs.control_helpers.load_config", lambda: _config())
    view = sii.TaskCreationView(MagicMock(), "c1")
    view.selected_cycle = "daily"
    view.selected_action = action
    view.selected_time = "04:00"
    view.add_item(view.create_button)
    return view


class TestA10AllowedActionsInUi:
    def test_allowed_actions_come_from_container_config(self, monkeypatch):
        service = MagicMock()
        service.get_all_servers.return_value = [
            {"docker_name": "c1", "allowed_actions": ["status", "stop", "restart"]},
        ]
        monkeypatch.setattr("services.config.server_config_service.get_server_config_service", lambda: service)
        assert sii._get_allowed_task_actions("c1") == ["stop", "restart"]
        assert sii._get_allowed_task_actions("unknown") == []

    async def test_action_dropdown_offers_only_allowed_actions(self, monkeypatch):
        monkeypatch.setattr(sii, "_get_allowed_task_actions", lambda name: ["start", "restart"])
        view = sii.TaskCreationView(MagicMock(), "c1")
        dropdown = sii.ActionDropdown(view.allowed_actions)
        assert [option.value for option in dropdown.options] == ["start", "restart"]

    async def test_add_task_button_refuses_without_allowed_actions(self, monkeypatch):
        monkeypatch.setattr(sii, "_get_allowed_task_actions", lambda name: [])
        interaction = _interaction()
        await sii.AddTaskButton(MagicMock(), "c1").callback(interaction)
        # Deferred first (R4-8), so the refusal is a followup
        interaction.response.defer.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()
        assert "view" not in interaction.followup.send.await_args.kwargs

    async def test_create_button_rejects_disallowed_action(self, monkeypatch):
        view = _ready_view(monkeypatch, allowed=["start"], action="stop")
        add = MagicMock(return_value=True)
        monkeypatch.setattr("services.scheduling.scheduler.add_task", add)
        interaction = _interaction()

        await view.create_button.callback(interaction)

        add.assert_not_called()
        assert "permission" in interaction.followup.send.await_args.args[0]


class TestA8ValidationErrorReported:
    async def test_schedule_validation_error_is_sent_to_user(self, monkeypatch):
        view = _ready_view(monkeypatch, allowed=["restart"])
        monkeypatch.setattr(sii, "load_config", lambda: _config(timezone="UTC"))

        def _raise(task):
            raise ScheduleValidationError("Cannot schedule task: it conflicts with another task")

        monkeypatch.setattr("services.scheduling.schedule_helpers.validate_task_before_creation", _raise)
        interaction = _interaction()

        await view.create_button.callback(interaction)

        interaction.followup.send.assert_awaited_once()
        assert "conflicts" in interaction.followup.send.await_args.args[0]


class TestA9ConfiguredTimezone:
    async def test_created_task_uses_configured_timezone(self, monkeypatch):
        view = _ready_view(monkeypatch, allowed=["restart"])
        monkeypatch.setattr(sii, "load_config", lambda: _config(timezone="America/New_York"))
        monkeypatch.setattr("services.scheduling.schedule_helpers.validate_task_before_creation", lambda task: None)
        monkeypatch.setattr("services.infrastructure.action_logger.log_user_action", lambda **kw: None)
        captured = {}

        def _fake_add(task):
            captured["task"] = task
            return True

        monkeypatch.setattr("services.scheduling.scheduler.add_task", _fake_add)
        interaction = _interaction()

        await view.create_button.callback(interaction)

        assert captured["task"].timezone_str == "America/New_York"
        embed = interaction.followup.send.await_args.kwargs["embed"]
        next_run = [field.value for field in embed.fields if "Next Run" in field.name][0]
        assert "04:00 E" in next_run  # EDT/EST

    async def test_delete_view_uses_configured_timezone(self, monkeypatch):
        monkeypatch.setattr(sii, "load_config", lambda: _config(timezone="America/New_York"))
        task = ScheduledTask(container_name="c1", action="restart", cycle="daily",
                             hour=4, minute=0, timezone_str="America/New_York")
        view = sii.ContainerTaskDeleteView(MagicMock(), [task], "c1")
        assert view.children[0].label.startswith("D:04h")
