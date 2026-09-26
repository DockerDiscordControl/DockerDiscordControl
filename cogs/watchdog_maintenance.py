# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Watchdog maintenance from Discord: the 🔧 button of the admin overview.

The same pauses the panel sets (services/automation/maintenance.py): pick a
container, pick how long, and the watchdog leaves it alone meanwhile - no
notice, no restart. The panel is private to whoever pressed the button.

WHO MAY: the admin list, like the other bulk buttons of the overview
(SPEC.md B2; tests/spec/test_the_bulk_buttons_answer_to_the_admin_list.py).
"""

from __future__ import annotations

import logging
import time

import discord
from discord.ui import Button, Select

from cogs.translation_manager import _
from utils.logging_utils import setup_logger

from .ddc_ui import NOTICE_STAYS_FOR, PrivateView

logger = setup_logger('ddc.watchdog_maintenance', level=logging.INFO)

DURATIONS = ((30, "30 min"), (60, "1 h"), (240, "4 h"))


def _containers():
    from services.config.server_config_service import get_server_config_service

    return [s.get('docker_name') for s in get_server_config_service().get_all_servers()
            if s.get('docker_name')][:25]


def maintenance_options(containers, pauses, clock=time.localtime):
    """The select's options: every container, a paused one marked with its end."""
    options = []
    for name in containers:
        pause = pauses.get(name)
        description = None
        if pause:
            description = _("In maintenance until {time}").format(
                time=time.strftime("%H:%M", clock(float(pause["until"]))))
        options.append(discord.SelectOption(label=name[:100], value=name[:100],
                                            description=description, emoji="🔧" if pause else None))
    return options


class AdminOverviewMaintenanceButton(Button):
    """🔧 on the admin overview: pause the watchdog for one container."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id
        super().__init__(style=discord.ButtonStyle.secondary, label=None, emoji="🔧",
                         custom_id=f"admin_overview_maintenance_{channel_id}",
                         # Row 0 holds five buttons already - Discord's maximum.
                         row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        from services.admin.admin_service import get_admin_service
        from services.automation.maintenance import pauses

        from .admin_overview import _admin_button_braked

        if await _admin_button_braked(interaction, "admin_overview_maintenance"):
            return
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.errors.NotFound, discord.errors.HTTPException) as e:
            logger.warning(f"Maintenance interaction could not be answered: {e}")
            return
        if not await get_admin_service().is_user_admin_async(str(interaction.user.id)):
            await interaction.followup.send(_("❌ Only admins can put a container into maintenance."),
                                            ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            return
        containers = [c for c in _containers() if _may_pause(interaction.user.id, c)]
        if not containers:
            await interaction.followup.send(_("❌ No containers configured."), ephemeral=True,
                                            delete_after=NOTICE_STAYS_FOR)
            return
        view = MaintenanceView(containers, pauses())
        view.message = await interaction.followup.send(
            _("🔧 **Watchdog maintenance** - pick a container and how long the watchdog leaves it alone. "
              "No notices, no restarts; the pause ends by itself."),
            view=view, ephemeral=True, wait=True)


def _may_pause(user_id, container: str) -> bool:
    """An admin, assigned this container or none (SPEC B2, operator 2026-09-26).
    Asked at every press - the private panel lives five minutes, and an admin
    list can change in that time."""
    from services.admin.admin_service import get_admin_service

    try:
        return bool(get_admin_service().may_control(str(user_id), container))
    except (ImportError, OSError, ValueError, RuntimeError) as e:
        logger.error(f"Admin assignment could not be read for {user_id}: {e}")
        return False


class ContainerMaintenanceButton(Button):
    """🔧 on a container's private admin panel (operator, 2026-09-26: "hang the
    maintenance button directly on the containers"). The container is already
    chosen there, so only the duration is asked. Green while it is paused."""

    def __init__(self, container: str, paused: bool = False):
        self.container = container
        super().__init__(style=discord.ButtonStyle.success if paused else discord.ButtonStyle.secondary,
                         label=None, emoji="🔧")

    async def callback(self, interaction: discord.Interaction) -> None:
        from services.admin.admin_service import get_admin_service
        from services.automation.maintenance import pauses

        if not _may_pause(interaction.user.id, self.container):
            await interaction.response.send_message(
                _("❌ Only admins can put a container into maintenance."),
                ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            return
        current = pauses()
        pause = current.get(self.container)
        text = (_("🔧 `{container}` is in maintenance until {time}.").format(
                    container=self.container,
                    time=time.strftime("%H:%M", time.localtime(float(pause["until"]))))
                if pause else
                _("🔧 How long should the watchdog leave `{container}` alone? "
                  "No notices, no restarts; the pause ends by itself.").format(container=self.container))
        await interaction.response.send_message(text, view=MaintenanceView([self.container], current,
                                                                           fixed=self.container),
                                                ephemeral=True)


class MaintenanceView(PrivateView):
    """Private to whoever pressed 🔧, so it carries its own close button (PrivateView).

    With ``fixed`` the container is already chosen (its own admin panel) and
    only the durations are offered; without it a select comes first."""

    def __init__(self, containers, current_pauses, fixed=None):
        super().__init__(timeout=300)
        self.chosen = fixed
        if fixed is None:
            self.select = Select(placeholder=_("Container"), min_values=1, max_values=1,
                                 options=maintenance_options(containers, current_pauses), row=0)
            self.select.callback = self._chosen
            self.add_item(self.select)
        for minutes, label in DURATIONS:
            button = Button(style=discord.ButtonStyle.primary, label=label, row=1)
            button.callback = self._pause_for(minutes)
            self.add_item(button)
        end = Button(style=discord.ButtonStyle.success, label=_("End maintenance"), row=1)
        end.callback = self._end
        self.add_item(end)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        self.chosen = self.select.values[0]
        await interaction.response.defer()

    async def _need_choice(self, interaction) -> bool:
        if self.chosen:
            return False
        await interaction.response.send_message(_("Pick a container first."), ephemeral=True,
                                                delete_after=NOTICE_STAYS_FOR)
        return True

    def _pause_for(self, minutes):
        async def callback(interaction: discord.Interaction) -> None:
            from services.automation.maintenance import pause
            from services.infrastructure.action_logger import log_user_action

            if await self._need_choice(interaction):
                return
            if not _may_pause(interaction.user.id, self.chosen):
                await interaction.response.send_message(
                    _("❌ Only admins can put a container into maintenance."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return
            until = pause(self.chosen, minutes, by=f"discord:{interaction.user.id}")
            log_user_action("MAINTENANCE", self.chosen, source=f"Discord, {minutes} min",
                            user=str(interaction.user))
            await interaction.response.send_message(
                _("🔧 `{container}` is in maintenance until {time} - the watchdog leaves it alone.").format(
                    container=self.chosen, time=time.strftime("%H:%M", time.localtime(until))),
                ephemeral=True, delete_after=NOTICE_STAYS_FOR)
        return callback

    async def _end(self, interaction: discord.Interaction) -> None:
        from services.automation.maintenance import resume
        from services.infrastructure.action_logger import log_user_action

        if await self._need_choice(interaction):
            return
        if not _may_pause(interaction.user.id, self.chosen):
            await interaction.response.send_message(
                _("❌ Only admins can put a container into maintenance."),
                ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            return
        ended = resume(self.chosen)
        if ended:
            log_user_action("MAINTENANCE_END", self.chosen, source="Discord", user=str(interaction.user))
        await interaction.response.send_message(
            (_("✅ Maintenance of `{container}` ended - the watchdog watches it again.") if ended
             else _("`{container}` was not in maintenance.")).format(container=self.chosen),
            ephemeral=True, delete_after=NOTICE_STAYS_FOR)
