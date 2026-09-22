# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Audit 2026-09 release review, package G1        #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Regression tests for the Discord task UI items of the release review.

R4-5 (delete panel shows each task in its own timezone with a marker) and
R4-8 (Add Task button acknowledges the interaction before the config lookup).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import cogs.status_info_integration as sii
from services.scheduling.scheduler import ScheduledTask


def _interaction():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.user = "tester"
    return interaction


class TestR4_8AddTaskDefersFirst:
    async def test_add_task_button_defers_before_the_lookup(self, monkeypatch):
        interaction = _interaction()

        def _lookup(name):
            # Discord must already be acknowledged while the configs are read
            assert interaction.response.defer.await_count == 1
            return ["restart"]

        monkeypatch.setattr(sii, "_get_allowed_task_actions", _lookup)
        monkeypatch.setattr("cogs.task_ui._get_allowed_task_actions", _lookup)  # moved there (Phase 3)

        await sii.AddTaskButton(MagicMock(), "c1").callback(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.response.send_message.assert_not_called()
        kwargs = interaction.followup.send.await_args.kwargs
        assert kwargs["ephemeral"] is True
        assert kwargs["view"].allowed_actions == ["restart"]
        assert "embed" in kwargs


class TestR4_5DeletePanelTaskTimezone:
    async def test_each_task_shows_its_own_timezone(self, monkeypatch):
        # Configured zone differs from the (older) Berlin task's zone
        monkeypatch.setattr(sii, "load_config", lambda: {"timezone": "America/New_York"})
        monkeypatch.setattr("cogs.task_ui.load_config", lambda: {"timezone": "America/New_York"})  # moved there (Phase 3)
        berlin = ScheduledTask(container_name="c1", action="restart", cycle="daily",
                               hour=4, minute=0, timezone_str="Europe/Berlin")
        new_york = ScheduledTask(container_name="c1", action="stop", cycle="daily",
                                 hour=4, minute=0, timezone_str="America/New_York")

        view = sii.ContainerTaskDeleteView(MagicMock(), [berlin, new_york], "c1")

        labels = [child.label for child in view.children]
        assert labels[0].startswith("D:04h CE")  # CET/CEST, not shifted to New York time
        assert labels[1].startswith("D:04h E")   # EST/EDT

    async def test_weekly_label_keeps_day_and_marker(self):
        task = ScheduledTask(container_name="c1", action="restart", cycle="weekly",
                             hour=4, minute=0, weekday=0, timezone_str="UTC")

        view = sii.ContainerTaskDeleteView(MagicMock(), [task], "c1")

        assert view.children[0].label == "W:Mo 04h UTC 🔄"
