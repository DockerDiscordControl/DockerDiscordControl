# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The task UI of the status channels: manage, create and delete scheduled tasks.

Moved out of cogs/status_info_integration.py unchanged on 2026-09-22 (roadmap
Phase 3, after the cog split): the task management button and view, the
creation view with its cycle/action/date/time dropdowns, the auto-action
button, and the per-container task deletion view. status_info_integration.py
re-exports every name.
"""

import asyncio
from typing import Any, Dict, List, Optional

import discord

from services.automation import get_auto_action_config_service
from services.config.config_service import load_config
from utils.logging_utils import get_module_logger

from .ddc_ui import DDCView
from .translation_manager import _

# Same logger name as before the move: log lines read as they did.
logger = get_module_logger('status_info_integration')


class TaskManagementButton(discord.ui.Button):
    """Task Management button for container info admin view."""

    def __init__(self, cog_instance, server_config: Dict[str, Any]):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="⏰",
            label=None,
            custom_id=f"task_management_{server_config.get('docker_name')}"
        )
        self.cog = cog_instance
        self.server_config = server_config
        self.container_name = server_config.get('docker_name')

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle task management button click."""
        try:
            # Try to defer immediately, but handle the case where interaction has already expired
            try:
                await interaction.response.defer(ephemeral=True)
                deferred = True
            except discord.errors.NotFound:
                # Interaction has already expired (>3 seconds)
                logger.warning(f"Task management interaction expired for {self.container_name}")
                return  # Can't send any response if interaction expired
            except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                logger.error(f"Error deferring task management interaction: {e}", exc_info=True)
                return

            # Check spam protection after deferring
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            # Through the service instead of an attribute on the button - same
            # reason as in InfoDropdownButton in control_ui.py. The lock lived on
            # the object and vanished with it; the per-minute limit from the
            # panel had no effect here, and the message was untranslated.
            if spam_service.is_enabled():
                try:
                    if spam_service.is_on_cooldown(interaction.user.id, "tasks"):
                        remaining = spam_service.get_remaining_cooldown(interaction.user.id, "tasks")
                        await interaction.followup.send(
                            _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                                remaining=remaining
                            ),
                            ephemeral=True
                        )
                        return
                    spam_service.add_user_cooldown(interaction.user.id, "tasks")
                except (RuntimeError, AttributeError, KeyError) as e:
                    logger.error(f"Spam protection error for task management button: {e}", exc_info=True)

            # Show task list directly
            await self._show_task_list(interaction)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in task management button: {e}", exc_info=True)
            try:
                await interaction.followup.send(_("❌ An error occurred. Please try again."), ephemeral=True)
            except Exception:
                pass

    async def _show_task_list(self, interaction: discord.Interaction):
        """Show task list for this container."""
        try:
            # Response already deferred in callback, no need to defer again

            # Get all tasks for this container
            from services.scheduling.scheduler import load_tasks, get_tasks_for_container

            tasks = get_tasks_for_container(self.container_name)

            if not tasks:
                embed = discord.Embed(
                    title=f"⏰ No Tasks for {self.container_name}",
                    description=_("No scheduled tasks found for this container."),
                    color=discord.Color.orange()
                )
                view = TaskManagementView(self.cog, self.container_name)
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                return

            # Create task list embed
            embed = discord.Embed(
                title=f"⏰ {_('Scheduled Tasks for {container}').format(container=self.container_name)}",
                color=discord.Color.blue()
            )

            for i, task in enumerate(tasks[:10]):  # Limit to 10 tasks to avoid embed size limits
                # Format last run
                last_run_str = _("Never")
                if task.last_run_ts:
                    from datetime import datetime
                    last_run_dt = datetime.fromtimestamp(task.last_run_ts)
                    last_run_str = last_run_dt.strftime("%Y-%m-%d %H:%M")
                    if task.last_run_success is not None:
                        status_icon = "✅" if task.last_run_success else "❌"
                        last_run_str += f" {status_icon}"

                # Format next run
                next_run_str = _("Not scheduled")
                if task.next_run_ts:
                    from datetime import datetime
                    next_run_dt = datetime.fromtimestamp(task.next_run_ts)
                    next_run_str = next_run_dt.strftime("%Y-%m-%d %H:%M")

                # Active status
                status_icon = "🟢" if task.is_active else "🔴"

                embed.add_field(
                    name=f"{status_icon} {task.action.upper()} - {task.cycle}",
                    value=f"**{_('Last Run')}:** {last_run_str}\n**{_('Next Run')}:** {next_run_str}\n**{_('ID')}:** `{task.task_id}`",
                    inline=False
                )

            if len(tasks) > 10:
                embed.set_footer(text=f"{_('Showing first {count} of {total} tasks').format(count=10, total=len(tasks))}")

            # Add management buttons
            view = TaskManagementView(self.cog, self.container_name)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing task list: {e}", exc_info=True)
            try:
                await interaction.followup.send(_("❌ An error occurred. Please try again."), ephemeral=True)
            except Exception:
                pass  # Interaction might have expired

class TaskManagementView(DDCView):
    """View with buttons for task management (Add Task, Delete Tasks, Auto-Action)."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog_instance
        self.container_name = container_name

        # Add Task button (green)
        self.add_item(AddTaskButton(cog_instance, container_name))

        # Delete Tasks button (red)
        self.add_item(DeleteTasksButton(cog_instance, container_name))

        # Auto-Action button (blue)
        self.add_item(AutoActionButton(cog_instance, container_name))

class AddTaskButton(discord.ui.Button):
    """Button to add a new scheduled task."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(
            style=discord.ButtonStyle.green,
            label=_("Add Task"),
            custom_id=f"add_task_{container_name}"
        )
        self.cog = cog_instance
        self.container_name = container_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show task creation with dropdowns."""
        try:
            logger.info(f"AddTaskButton clicked for container: {self.container_name}")

            # Acknowledge first: the allowed-actions lookup reads all container
            # configs and could outlast Discord's 3 s limit (10062 Unknown interaction)
            await interaction.response.defer(ephemeral=True)
            allowed_actions = await asyncio.to_thread(_get_allowed_task_actions, self.container_name)

            # Create dropdown-based task creation
            view = TaskCreationView(self.cog, self.container_name, allowed_actions=allowed_actions)
            if not view.allowed_actions:
                await interaction.followup.send(
                    f"❌ {_('No schedulable actions (start/stop/restart) are allowed for {container}.').format(container=self.container_name)}",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title=f"⏰ {_('Create Task: {container}').format(container=self.container_name)}",
                description=_("Use the dropdowns below to configure your task:"),
                color=discord.Color.green()
            )

            embed.add_field(
                name=f"📋 {_('Instructions')}",
                value=_("1. Select Cycle Type\n2. Select Action\n3. Select Time and day/date\n4. Click 'Create Task'"),
                inline=False
            )

            await interaction.followup.send(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in add task button: {e}", exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {_('Error showing task help.')}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {_('Error showing task help.')}", ephemeral=True)

class DeleteTasksButton(discord.ui.Button):
    """Button to open task delete panel."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(
            style=discord.ButtonStyle.red,
            label=_("Delete Tasks"),
            custom_id=f"delete_tasks_{container_name}"
        )
        self.cog = cog_instance
        self.container_name = container_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open task delete panel using existing /task_delete_panel functionality."""
        try:
            await interaction.response.defer(ephemeral=True)

            # Call the existing task delete panel functionality
            # This will use the same logic as the /task_delete_panel command
            from services.scheduling.scheduler import load_tasks, get_tasks_for_container

            tasks = get_tasks_for_container(self.container_name)

            if not tasks:
                await interaction.followup.send(
                    _("⏰ No tasks found for {name} to delete.").format(name=self.container_name),
                    ephemeral=True
                )
                return

            # Create container-specific task delete view
            view = ContainerTaskDeleteView(self.cog, tasks, self.container_name)

            embed = discord.Embed(
                title=f"❌ {_('Delete Tasks: {container}').format(container=self.container_name)}",
                description=f"{_('Click any button below to delete the corresponding task for **{container}**:').format(container=self.container_name)}",
                color=discord.Color.red()
            )

            # Add legend
            embed.add_field(
                name=_("Legend"),
                value=_("O = Once, D = Daily, W = Weekly, M = Monthly, Y = Yearly"),
                inline=False
            )

            embed.add_field(
                name=_("Found Tasks"),
                value=f"{_('{count} active tasks for {container}').format(count=len(tasks), container=self.container_name)}",
                inline=False
            )

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in delete tasks button: {e}", exc_info=True)
            await interaction.followup.send(f"❌ {_('Error opening task delete panel.')}", ephemeral=True)


class AutoActionButton(discord.ui.Button):
    """Button to show Auto-Actions affecting this container."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(
            style=discord.ButtonStyle.blurple,
            label=_("Auto-Action"),
            custom_id=f"auto_action_{container_name}"
        )
        self.cog = cog_instance
        self.container_name = container_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show all Auto-Actions that affect this container."""
        try:
            await interaction.response.defer(ephemeral=True)

            # Get Auto-Action rules from config service
            config_service = get_auto_action_config_service()
            all_rules = config_service.get_rules()

            # Filter rules that target this container - groups resolved. A rule
            # aimed at "group:Gameserver" WILL act on this container, and
            # reading the raw list answered "no Auto-Actions configured" while
            # an automation was wired to it.
            from services.automation.automation_service import containers_of_action

            matching_rules = [
                rule for rule in all_rules
                if self.container_name in containers_of_action(rule)
            ]

            if not matching_rules:
                embed = discord.Embed(
                    title=f"🤖 {_('Auto-Actions for {container}').format(container=self.container_name)}",
                    description=_("No Auto-Actions configured for this container."),
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Create embed with matching rules
            embed = discord.Embed(
                title=f"🤖 {_('Auto-Actions for {container}').format(container=self.container_name)}",
                description=f"{_('Found {count} Auto-Action(s) targeting this container:').format(count=len(matching_rules))}",
                color=discord.Color.blue()
            )

            for rule in matching_rules[:10]:  # Limit to 10 rules
                # Status icon
                status_icon = "🟢" if rule.enabled else "🔴"

                # Action emoji
                action_emojis = {
                    "RESTART": "🔄",
                    "STOP": "⏹️",
                    "START": "▶️",
                    "NOTIFY": "📢"
                }
                action_emoji = action_emojis.get(rule.action.type, "⚡")

                # Keywords preview (max 3)
                keywords_preview = ", ".join(rule.trigger.keywords[:3])
                if len(rule.trigger.keywords) > 3:
                    keywords_preview += f" (+{len(rule.trigger.keywords) - 3})"

                # Build field value
                field_value = (
                    f"**{_('Action')}:** {action_emoji} {rule.action.type}\n"
                    f"**{_('Keywords')}:** `{keywords_preview or _('None')}`\n"
                    f"**{_('Cooldown')}:** {rule.cooldown_minutes} min\n"
                    f"**{_('Priority')}:** {rule.priority}"
                )

                if rule.trigger.regex_pattern:
                    regex_preview = rule.trigger.regex_pattern[:30]
                    if len(rule.trigger.regex_pattern) > 30:
                        regex_preview += "..."
                    field_value += f"\n**Regex:** `{regex_preview}`"

                embed.add_field(
                    name=f"{status_icon} {rule.name}",
                    value=field_value,
                    inline=True
                )

            # Add footer with hint
            embed.set_footer(text=_("Manage Auto-Actions in the Web UI"))

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in auto action button: {e}", exc_info=True)
            await interaction.followup.send(f"❌ {_('Error loading Auto-Actions.')}", ephemeral=True)


# Actions that can be scheduled as tasks (services.scheduling.scheduler.VALID_ACTIONS)
_TASK_ACTIONS = ("start", "stop", "restart")


def _get_allowed_task_actions(container_name: str) -> List[str]:
    """Return the schedulable actions allowed for a container (its allowed_actions)."""
    try:
        from services.config.server_config_service import get_server_config_service
        for server in get_server_config_service().get_all_servers():
            if server.get('docker_name') == container_name:
                allowed = server.get('allowed_actions') or []
                return [action for action in _TASK_ACTIONS if action in allowed]
    except (ImportError, AttributeError, RuntimeError, OSError, ValueError) as e:
        logger.error(f"Error loading allowed actions for {container_name}: {e}", exc_info=True)
    return []


class TaskCreationView(DDCView):
    """View for task creation using sequential dropdowns."""

    def __init__(self, cog_instance, container_name: str, allowed_actions: Optional[List[str]] = None):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.container_name = container_name
        # Only actions the container allows may be scheduled (looked up if not given)
        self.allowed_actions = (allowed_actions if allowed_actions is not None
                                else _get_allowed_task_actions(container_name))

        # Task configuration state
        self.selected_cycle = None
        self.selected_action = None
        self.selected_time = None
        self.selected_day = None
        self.selected_month = None
        self.selected_year = None

        # Start with only cycle dropdown
        self.add_item(CycleDropdown())

        # Add create button (initially disabled and hidden)
        self.create_button = CreateTaskButton(self.cog, self.container_name)
        self.create_button.disabled = True
        self.create_button.row = 4  # Always on the last row

    def check_ready(self):
        """Check if all required fields are selected and enable create button."""
        if self.selected_cycle == 'daily':
            ready = self.selected_action and self.selected_time
        elif self.selected_cycle == 'weekly':
            ready = self.selected_action and self.selected_day and self.selected_time
        elif self.selected_cycle == 'monthly':
            ready = self.selected_action and self.selected_day and self.selected_time
        elif self.selected_cycle == 'yearly':
            ready = self.selected_action and self.selected_day and self.selected_month and self.selected_time
        elif self.selected_cycle == 'once':
            ready = self.selected_action and self.selected_day and self.selected_month and self.selected_year and self.selected_time
        else:
            ready = False

        # Add or update create button
        if ready:
            if self.create_button not in self.children:
                self.create_button.row = 4  # Ensure it's always on row 4
                self.add_item(self.create_button)
            self.create_button.disabled = False
        else:
            if self.create_button in self.children:
                self.create_button.disabled = True

    def clear_dropdowns_after(self, keep_until_row: int):
        """Remove all dropdowns after a certain row."""
        items_to_remove = []
        for item in self.children:
            if hasattr(item, 'row') and item.row is not None and item.row > keep_until_row and item != self.create_button:
                items_to_remove.append(item)
        for item in items_to_remove:
            self.remove_item(item)

    def get_next_available_row(self):
        """Get the next available row for a dropdown."""
        # Find the highest row number in use
        max_row = -1
        for item in self.children:
            if item != self.create_button and not isinstance(item, discord.ui.Button):
                if hasattr(item, 'row') and item.row is not None:
                    max_row = max(max_row, item.row)

        # Return the next row (but max 3 for dropdowns, keeping 4 for button)
        next_row = max_row + 1
        if next_row > 3:
            # If we're out of rows, we need to remove some dropdowns first
            logger.warning(f"No more rows available! Max row in use: {max_row}")
            return 3
        return next_row


class CycleDropdown(discord.ui.Select):
    """Dropdown for selecting task cycle."""

    def __init__(self):
        options = [
            discord.SelectOption(label=_("Daily"), description=_("Run every day"), emoji="📅", value="daily"),
            discord.SelectOption(label=_("Weekly"), description=_("Run weekly on specific day"), emoji="📆", value="weekly"),
            discord.SelectOption(label=_("Monthly"), description=_("Run monthly on specific day"), emoji="🗓️", value="monthly"),
            discord.SelectOption(label=_("Yearly"), description=_("Run yearly on specific date"), emoji="📊", value="yearly"),
            discord.SelectOption(label=_("Once"), description=_("Run once at specific date"), emoji="⚡", value="once")
        ]

        super().__init__(placeholder=_("Choose cycle type..."), options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle cycle selection and show action dropdown."""
        self.view.selected_cycle = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(0)

        # Reset selections
        self.view.selected_action = None
        self.view.selected_day = None
        self.view.selected_month = None
        self.view.selected_year = None
        self.view.selected_time = None

        # Add action dropdown
        action_dropdown = ActionDropdown(self.view.allowed_actions)
        action_dropdown.row = self.view.get_next_available_row()
        self.view.add_item(action_dropdown)

        embed = discord.Embed(
            title=f"⏰ {_('Create Task: {container}').format(container=self.view.container_name)}",
            description=f"✅ **{_('Cycle')}:** {self.values[0].title()}\n\n{_('Now choose the action...')}",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class ActionDropdown(discord.ui.Select):
    """Dropdown for selecting task action."""

    def __init__(self, allowed_actions: Optional[List[str]] = None):
        options = [
            discord.SelectOption(label=_("Start"), description=_("Start the container"), emoji="▶️", value="start"),
            discord.SelectOption(label=_("Stop"), description=_("Stop the container"), emoji="⏹️", value="stop"),
            discord.SelectOption(label=_("Restart"), description=_("Restart the container"), emoji="🔄", value="restart")
        ]
        # Only offer actions the container's config allows
        if allowed_actions is not None:
            options = [option for option in options if option.value in allowed_actions]

        super().__init__(placeholder=_("Choose action..."), options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle action selection and show next dropdown based on cycle."""
        self.view.selected_action = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(self.row if hasattr(self, 'row') else 1)

        # Reset subsequent selections
        self.view.selected_day = None
        self.view.selected_month = None
        self.view.selected_year = None
        self.view.selected_time = None

        # Add next dropdown based on cycle type
        if self.view.selected_cycle == 'daily':
            # Daily only needs time
            time_dropdown = TimeDropdown()
            time_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(time_dropdown)
        elif self.view.selected_cycle == 'weekly':
            # Weekly needs weekday first
            weekday_dropdown = WeekdayDropdown()
            weekday_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(weekday_dropdown)
        elif self.view.selected_cycle == 'monthly':
            # Monthly needs day of month first
            day_dropdown = SimpleMonthdayDropdown()
            day_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(day_dropdown)
        elif self.view.selected_cycle == 'yearly':
            # Yearly needs day first
            day_dropdown = SimpleMonthdayDropdown()
            day_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(day_dropdown)
        elif self.view.selected_cycle == 'once':
            # Once needs day first
            day_dropdown = SimpleMonthdayDropdown()
            day_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(day_dropdown)

        embed = discord.Embed(
            title=f"⏰ {_('Create Task: {container}').format(container=self.view.container_name)}",
            description=f"✅ **{_('Cycle')}:** {self.view.selected_cycle.title()}\n✅ **{_('Action')}:** {self.values[0].title()}\n\n{_('Continue with the next selection...')}",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

FIRST_PAGE_LAST_DAY = 24   # 24 days plus the option that turns the page = 25
LATER_DAYS = "later_days"
EARLIER_DAYS = "earlier_days"


class SimpleMonthdayDropdown(discord.ui.Select):
    """Day of the month, 1-31, in two pages.

    Discord shows at most 25 options in one select, and a month has 31 days.
    The list used to hold 24 hand-picked days and simply left out the 5th, 6th,
    11th, 17th, 18th, 26th and 29th - no hint, no reason, and for the 29th and
    31st no way at all to schedule a task at the end of the month (review B21).
    Now the first page carries the days 1-24 and a last option that turns to
    25-31, which in turn offers the way back.
    """

    def __init__(self, page: int = 1):
        self.page = page
        if page == 1:
            options = [discord.SelectOption(label=f"{day:02d}", value=str(day))
                       for day in range(1, FIRST_PAGE_LAST_DAY + 1)]
            # Numbers and an arrow, deliberately without _(): the label carries no
            # words, so it needs no entry in the 41 catalogs and reads the same in
            # every language.
            options.append(discord.SelectOption(label="25 - 31  →", value=LATER_DAYS))
        else:
            options = [discord.SelectOption(label="←  1 - 24", value=EARLIER_DAYS)]
            options += [discord.SelectOption(label=f"{day:02d}", value=str(day))
                        for day in range(FIRST_PAGE_LAST_DAY + 1, 32)]

        # Dynamic row assignment to avoid conflicts
        super().__init__(placeholder=_("Choose day..."), options=options)

    async def _turn_page(self, interaction: discord.Interaction) -> None:
        """Swap this dropdown for the other page, in the same row."""
        row = getattr(self, 'row', None)
        self.view.remove_item(self)
        other_page = SimpleMonthdayDropdown(page=2 if self.values[0] == LATER_DAYS else 1)
        if row is not None:
            other_page.row = row
        self.view.add_item(other_page)
        await interaction.response.edit_message(view=self.view)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle day selection."""
        if self.values[0] in (LATER_DAYS, EARLIER_DAYS):
            await self._turn_page(interaction)
            return

        self.view.selected_day = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(self.row if hasattr(self, 'row') else 2)

        # Add next dropdown based on cycle
        if self.view.selected_cycle == 'monthly':
            # Monthly: after day comes time
            # Remove day dropdown to make room (value already saved)
            self.view.remove_item(self)

            time_dropdown = TimeDropdown()
            time_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(time_dropdown)
        elif self.view.selected_cycle == 'yearly':
            # Yearly: after day comes month
            month_dropdown = MonthDropdown()
            month_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(month_dropdown)
        elif self.view.selected_cycle == 'once':
            # Once: after day comes month
            month_dropdown = MonthDropdown()
            month_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(month_dropdown)

        embed = discord.Embed(
            title=f"⏰ {_('Create Task: {container}').format(container=self.view.container_name)}",
            description=f"✅ **{_('Cycle')}:** {self.view.selected_cycle.title()}\n✅ **{_('Action')}:** {self.view.selected_action.title()}\n✅ **{_('Day')}:** {self.values[0]}\n\n{_('Continue...')}",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class MonthDropdown(discord.ui.Select):
    """Dropdown for selecting month."""

    def __init__(self):
        months = [
            _("January"), _("February"), _("March"), _("April"), _("May"), _("June"),
            _("July"), _("August"), _("September"), _("October"), _("November"), _("December")
        ]

        options = []
        for i, month in enumerate(months, 1):
            options.append(discord.SelectOption(
                label=month,
                value=str(i)
            ))

        # Dynamic row assignment
        super().__init__(placeholder=_("Choose month..."), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle month selection."""
        self.view.selected_month = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(self.row if hasattr(self, 'row') else 3)

        # Add next dropdown based on cycle
        if self.view.selected_cycle == 'yearly':
            # Yearly: after month comes time
            # Remove day and month dropdowns to make room (values already saved)
            items_to_remove = []
            for item in self.view.children:
                if isinstance(item, (SimpleMonthdayDropdown, MonthDropdown)):
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.view.remove_item(item)

            # Now add time dropdown
            time_dropdown = TimeDropdown()
            time_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(time_dropdown)
        elif self.view.selected_cycle == 'once':
            # Once: after month comes year
            # Remove day AND month dropdowns to make room (values already saved)
            items_to_remove = []
            for item in self.view.children:
                if isinstance(item, (SimpleMonthdayDropdown, MonthDropdown)):
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.view.remove_item(item)

            year_dropdown = YearDropdown()
            year_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(year_dropdown)

        embed = discord.Embed(
            title=f"⏰ {_('Create Task: {container}').format(container=self.view.container_name)}",
            description=f"✅ **{_('Cycle')}:** {self.view.selected_cycle.title()}\n✅ **{_('Action')}:** {self.view.selected_action.title()}\n✅ **{_('Day')}:** {self.view.selected_day}\n✅ **{_('Month')}:** {self.values[0]}\n\n{_('Continue...')}",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class YearDropdown(discord.ui.Select):
    """Dropdown for selecting year."""

    def __init__(self):
        from datetime import datetime
        current_year = datetime.now().year

        options = []
        for year in range(current_year, current_year + 11):  # Current year + 10 years
            options.append(discord.SelectOption(
                label=str(year),
                value=str(year)
            ))

        # Dynamic row assignment
        super().__init__(placeholder=_("Choose year..."), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle year selection."""
        self.view.selected_year = self.values[0]

        # After year comes time (for once)
        # Remove previous dropdowns to make room (values already saved)
        items_to_remove = []
        for item in self.view.children:
            if isinstance(item, (SimpleMonthdayDropdown, MonthDropdown, YearDropdown)):
                items_to_remove.append(item)
        for item in items_to_remove:
            self.view.remove_item(item)

        time_dropdown = TimeDropdown()
        time_dropdown.row = self.view.get_next_available_row()
        self.view.add_item(time_dropdown)

        embed = discord.Embed(
            title=f"⏰ {_('Create Task: {container}').format(container=self.view.container_name)}",
            description=f"✅ **{_('Cycle')}:** {self.view.selected_cycle.title()}\n✅ **{_('Action')}:** {self.view.selected_action.title()}\n✅ **{_('Day')}:** {self.view.selected_day}\n✅ **{_('Month')}:** {self.view.selected_month}\n✅ **{_('Year')}:** {self.values[0]}\n\n{_('Now choose the time...')}",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class TimeDropdown(discord.ui.Select):
    """Dropdown for selecting task time."""

    def __init__(self):
        # Common times throughout the day
        times = []
        for hour in range(0, 24):  # Every hour
            time_str = f"{hour:02d}:00"
            label = f"{time_str}"
            times.append(discord.SelectOption(label=label, value=time_str))

        # Dynamic row assignment
        super().__init__(placeholder=_("Choose time..."), options=times[:24])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle time selection - final step."""
        self.view.selected_time = self.values[0]
        self.view.check_ready()

        # Build summary of selections
        summary = [f"✅ **{_('Cycle:')}** {_(self.view.selected_cycle.title())}"]
        summary.append(f"✅ **{_('Action:')}** {_(self.view.selected_action.title())}")

        if self.view.selected_cycle == 'weekly':
            summary.append(f"✅ **{_('Weekday:')}** {_(self.view.selected_day.title())}")
        elif self.view.selected_cycle in ['monthly', 'yearly', 'once']:
            summary.append(f"✅ **{_('Day:')}** {self.view.selected_day}")

        if self.view.selected_cycle in ['yearly', 'once']:
            # Get month name
            months = [_("January"), _("February"), _("March"), _("April"), _("May"), _("June"),
                     _("July"), _("August"), _("September"), _("October"), _("November"), _("December")]
            month_name = months[int(self.view.selected_month) - 1]
            summary.append(f"✅ **{_('Month:')}** {month_name}")

        if self.view.selected_cycle == 'once':
            summary.append(f"✅ **{_('Year:')}** {self.view.selected_year}")

        summary.append(f"✅ **{_('Time:')}** {self.values[0]}")

        embed = discord.Embed(
            title=f"⏰ {_('Create Task: {container}').format(container=self.view.container_name)}",
            description="\n".join(summary) + f"\n\n**{_('Task configuration complete! Click Create Task to save.')}**",
            color=discord.Color.green()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class WeekdayDropdown(discord.ui.Select):
    """Dropdown for selecting weekday."""

    def __init__(self):
        options = [
            discord.SelectOption(label=_("Monday"), value="monday"),
            discord.SelectOption(label=_("Tuesday"), value="tuesday"),
            discord.SelectOption(label=_("Wednesday"), value="wednesday"),
            discord.SelectOption(label=_("Thursday"), value="thursday"),
            discord.SelectOption(label=_("Friday"), value="friday"),
            discord.SelectOption(label=_("Saturday"), value="saturday"),
            discord.SelectOption(label=_("Sunday"), value="sunday")
        ]

        # Dynamic row assignment
        super().__init__(placeholder=_("Choose weekday..."), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle weekday selection."""
        self.view.selected_day = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(self.row if hasattr(self, 'row') else 2)

        # Add time dropdown (final step for weekly)
        # Remove weekday dropdown to make room (value already saved)
        self.view.remove_item(self)

        time_dropdown = TimeDropdown()
        time_dropdown.row = self.view.get_next_available_row()
        self.view.add_item(time_dropdown)

        embed = discord.Embed(
            title=f"⏰ {_('Create Task: {container}').format(container=self.view.container_name)}",
            description=f"✅ **{_('Cycle')}:** {self.view.selected_cycle.title()}\n✅ **{_('Action')}:** {self.view.selected_action.title()}\n✅ **{_('Weekday')}:** {self.values[0].title()}\n\n{_('Now choose the time...')}",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

# Seven classes stood here (1979-2264): MonthdayDropdown, YeardayDropdown,
# ManualDateView, DaySelectDropdown, MonthSelectDropdown, ConfirmDateButton and
# DateDropdown - a second, older way to pick a date that nothing ever built. It
# stored a date as one "DD.MM" string, which CreateTaskButton below reads with
# int(), and its day list cut 1-31 down to the first 25 with options[:25]. Both
# would have been real defects on a path a user can reach; here they were a trap
# for whoever reads the file (review B22). The live way asks for day and month
# separately: SimpleMonthdayDropdown + MonthDropdown.

class CreateTaskButton(discord.ui.Button):
    """Button to directly create the task."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=_("Create Task"),
            emoji="✅"
            # Row will be set dynamically when adding to view
        )
        self.cog = cog_instance
        self.container_name = container_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Directly create task with selected parameters."""
        # Validate all required fields
        missing = []
        if not self.view.selected_cycle:
            missing.append(_("Cycle"))
        if not self.view.selected_action:
            missing.append(_("Action"))
        if not self.view.selected_time:
            missing.append(_("Time"))
        if self.view.selected_cycle in ['weekly', 'monthly', 'yearly', 'once'] and not self.view.selected_day:
            missing.append(_("Day/Date"))

        if missing:
            await interaction.response.send_message(f"❌ {_('Please select: {missing}').format(missing=', '.join(missing))}", ephemeral=True)
            return

        # Imported before try so the except clause below can reference it
        from services.scheduling.schedule_helpers import ScheduleValidationError

        try:
            await interaction.response.defer(ephemeral=True)

            # The channel's CURRENT 'schedule' permission, or a registered admin
            # (SPEC.md B2) - the same rule as the twin that DELETES a task
            # (ContainerTaskDeleteButton). Creating one was checked nowhere: neither
            # at the click nor here, so the same thing needed a permission on one path
            # and none on the other, and a view still open after a revocation kept
            # creating tasks for up to ~890 s (SPEC.md Z5, review B3).
            # An assigned admin may only make tasks for their own containers
            # (review F2); the channel branch in front of it is untouched.
            from .control_helpers import _channel_has_permission, _admin_may_control
            if not (_channel_has_permission(interaction.channel_id, 'schedule', load_config())
                    or _admin_may_control(interaction.user.id, self.container_name)):
                await interaction.followup.send(
                    f"❌ {_('This action is not allowed in this channel.')}",
                    ephemeral=True
                )
                return

            # Re-check allowed actions at creation time (config may have changed)
            if self.view.selected_action not in _get_allowed_task_actions(self.container_name):
                error_msg = _("You don't have permission to perform '{action}' on '{container}'.").format(
                    action=self.view.selected_action, container=self.container_name
                )
                await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
                return

            # Import required modules
            from services.scheduling.scheduler import ScheduledTask, add_task, parse_time_string, parse_weekday_string
            from services.scheduling.schedule_helpers import validate_task_before_creation
            from services.infrastructure.action_logger import log_user_action
            import uuid
            import time

            # Parse time
            hour, minute = parse_time_string(self.view.selected_time)

            # Parse day/date based on cycle type
            day_val = None
            weekday_val = None
            month_val = None
            year_val = None

            if self.view.selected_cycle == 'weekly':
                weekday_val = parse_weekday_string(self.view.selected_day)
            elif self.view.selected_cycle == 'monthly':
                day_val = int(self.view.selected_day)
            elif self.view.selected_cycle == 'yearly':
                # We now have separate day and month fields
                day_val = int(self.view.selected_day)
                month_val = int(self.view.selected_month)
            elif self.view.selected_cycle == 'once':
                # We now have separate day, month and year fields
                day_val = int(self.view.selected_day)
                month_val = int(self.view.selected_month)
                year_val = int(self.view.selected_year)

            # Create ScheduledTask
            task = ScheduledTask(
                task_id=str(uuid.uuid4()),
                container_name=self.container_name,
                action=self.view.selected_action,
                cycle=self.view.selected_cycle,
                hour=hour,
                minute=minute,
                day=day_val if self.view.selected_cycle != 'weekly' else None,
                weekday=weekday_val,
                month=month_val if self.view.selected_cycle in ['yearly', 'once'] else None,
                year=year_val if self.view.selected_cycle == 'once' else None,
                created_by=str(interaction.user),
                created_at=time.time(),
                # Configured timezone, like the slash commands
                timezone_str=load_config().get('timezone', 'Europe/Berlin')
            )

            # Calculate next run time
            task.calculate_next_run()

            # Validate and save
            validate_task_before_creation(task)

            if add_task(task):
                # Log the action
                log_user_action(
                    action="TASK_CREATE_BUTTON",
                    target=self.container_name,
                    user=str(interaction.user),
                    source="Task Button",
                    details=f"Action: {self.view.selected_action}, Cycle: {self.view.selected_cycle}, Time: {self.view.selected_time}"
                )

                # Success embed
                embed = discord.Embed(
                    title=f"✅ {_('Task Created Successfully!')}",
                    description=f"{_('Task has been created for **{container}**').format(container=self.container_name)}",
                    color=discord.Color.green()
                )

                embed.add_field(
                    name=f"📋 {_('Configuration')}",
                    value=f"**{_('Action')}:** {_(self.view.selected_action.title())}\n"
                          f"**{_('Cycle')}:** {_(self.view.selected_cycle.title())}\n"
                          f"**{_('Time')}:** {self.view.selected_time}\n" +
                          (f"**{_('Day/Date')}:** {self.view.selected_day}" if self.view.selected_day else ""),
                    inline=False
                )

                # Format next run time (in the task's timezone, i.e. the configured one)
                next_run_dt = task.get_next_run_datetime()
                if next_run_dt:
                    next_run = next_run_dt.strftime('%Y-%m-%d %H:%M %Z')
                    embed.add_field(
                        name=f"⏰ {_('Next Run')}",
                        value=f"`{next_run}`",
                        inline=True
                    )

                embed.add_field(
                    name=f"🔍 {_('Task ID')}",
                    value=f"`{task.task_id}`",
                    inline=True
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

            else:
                await interaction.followup.send(
                    f"❌ {_('Failed to create task. Please check for time conflicts or try again.')}",
                    ephemeral=True
                )

        except ScheduleValidationError as e:
            # Validation messages are user-facing (e.g. time conflict, time in the past)
            logger.info(f"Task creation for {self.container_name} rejected: {e}")
            await interaction.followup.send(f"❌ **{_('Error')}**: {str(e)[:200]}", ephemeral=True)
        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error creating task: {e}", exc_info=True)
            error_msg = str(e)
            if "collision" in error_msg.lower():
                await interaction.followup.send(
                    f"❌ **{_('Time Conflict')}**: {_('Another task is already scheduled within 10 minutes of this time for {container}').format(container=self.container_name)}.",
                    ephemeral=True
                )
            elif "past" in error_msg.lower():
                await interaction.followup.send(
                    f"❌ **{_('Invalid Time')}**: {_('The scheduled time is in the past. Please select a future time.')}.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ **{_('Error')}**: {error_msg[:200]}",
                    ephemeral=True
                )


class ContainerTaskDeleteView(DDCView):
    """View for deleting tasks specific to a container."""

    def __init__(self, cog_instance, tasks: list, container_name: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog_instance
        self.container_name = container_name

        # Add delete buttons for each task (max 25 due to Discord limits)
        max_tasks = min(len(tasks), 25)
        for i, task in enumerate(tasks[:max_tasks]):
            task_id = task.task_id

            # Create detailed description for button
            action = task.action.upper()
            cycle_abbrev = {
                'once': 'O',
                'daily': 'D',
                'weekly': 'W',
                'monthly': 'M',
                'yearly': 'Y'
            }.get(task.cycle, '?')

            # Get action emoji
            action_emojis = {
                'START': '▶️',
                'STOP': '⏹️',
                'RESTART': '🔄'
            }
            action_emoji = action_emojis.get(action, '⚙️')

            # Build detailed time and date info in the task's own timezone (older
            # tasks may use another zone than the configured one), with a marker
            time_info = ""
            next_run = task.get_next_run_datetime() if getattr(task, 'next_run_ts', None) else None
            if next_run:
                if task.cycle == 'once':
                    # For once: show full date and time "O:13.08.27 14h"
                    time_info = f":{next_run.strftime('%d.%m.%y %Hh')}"
                elif task.cycle == 'daily':
                    # For daily: show hour "D:17h"
                    time_info = f":{next_run.strftime('%Hh')}"
                elif task.cycle == 'weekly':
                    # For weekly: show day and hour "W:Mo 17h"
                    weekday_abbrev = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][next_run.weekday()]
                    time_info = f":{weekday_abbrev} {next_run.strftime('%Hh')}"
                elif task.cycle == 'monthly':
                    # For monthly: show day and hour "M:15. 17h"
                    time_info = f":{next_run.strftime('%d. %Hh')}"
                elif task.cycle == 'yearly':
                    # For yearly: show month.day and hour "Y:13.08 22h"
                    time_info = f":{next_run.strftime('%d.%m %Hh')}"
                else:
                    # Fallback: just show time
                    time_info = f":{next_run.strftime('%Hh')}"
                tz_marker = next_run.strftime('%Z')
                if tz_marker:
                    time_info += f" {tz_marker}"
            elif hasattr(task, 'time_str') and task.time_str:
                # Fallback to time_str if available
                time_info = f":{task.time_str}"

            task_description = f"{cycle_abbrev}{time_info} {action_emoji}"

            # Limit description length for button
            if len(task_description) > 35:
                task_description = task_description[:32] + "..."

            row = i // 5  # 5 buttons per row
            self.add_item(ContainerTaskDeleteButton(cog_instance, task_id, task_description, row))

class ContainerTaskDeleteButton(discord.ui.Button):
    """Button to delete a specific task."""

    def __init__(self, cog_instance, task_id: str, description: str, row: int):
        super().__init__(
            style=discord.ButtonStyle.red,
            label=description,
            custom_id=f"delete_task_{task_id}",
            row=row
        )
        self.cog = cog_instance
        self.task_id = task_id
        self.description = description

    async def callback(self, interaction: discord.Interaction) -> None:
        """Delete the task."""
        try:
            await interaction.response.defer(ephemeral=True)

            from services.scheduling.scheduler import delete_task, find_task_by_id
            from services.infrastructure.action_logger import log_user_action
            from .control_helpers import _channel_has_permission, _admin_may_control_task

            # Deleting a scheduled task needs the 'schedule' permission of the
            # CURRENT channel. The twin button in control_ui.py:1276 checks it;
            # this path did not, so whoever held 'control' but deliberately not
            # 'schedule' could still delete tasks here. Same action, same right.
            # See SPEC.md Z5 - the assurance holds on EVERY path or not at all.
            # A registered admin may delete as well (SPEC.md B2): this is the
            # button of the admin info view, which admins open in status
            # channels. Added 2026-09-19 after the operator was refused there.
            config = load_config()
            # Via the task's container - same rule as its twin in control_ui
            # (review F2).
            if not (_channel_has_permission(interaction.channel_id, 'schedule', config)
                    or _admin_may_control_task(interaction.user.id, self.task_id)):
                await interaction.followup.send(
                    f"❌ {_('You do not have permission to delete tasks in this channel.')}",
                    ephemeral=True
                )
                return

            # Find the task first to get info for logging
            task = find_task_by_id(self.task_id)
            if not task:
                await interaction.followup.send(
                    f"❌ {_('Task not found (may have already been deleted)')}",
                    ephemeral=True
                )
                return

            # Delete the task
            success = delete_task(self.task_id)

            if success:
                # Log the action
                log_user_action(
                    action="TASK_DELETE_BUTTON",
                    target=task.container_name,
                    user=str(interaction.user),
                    source="Task Delete Button",
                    details=f"Deleted task: {task.cycle} {task.action} for {task.container_name}"
                )

                # Success response
                embed = discord.Embed(
                    title=f"✅ {_('Task Deleted')}",
                    description=f"{_('Successfully deleted task: **{description}**').format(description=self.description)}",
                    color=discord.Color.green()
                )

                embed.add_field(
                    name=_('Task Details'),
                    value=f"{_('Container')}: {task.container_name}\n{_('Action')}: {_(task.action.title())}\n{_('Cycle')}: {_(task.cycle.title())}",
                    inline=False
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

                # Remove this button from the view
                self.view.remove_item(self)

                # Update the original message to remove the deleted task button
                try:
                    await interaction.edit_original_response(view=self.view)
                except Exception:
                    # If editing fails, it's not critical
                    pass

            else:
                await interaction.followup.send(
                    f"❌ {_('Failed to delete task: **{description}**').format(description=self.description)}",
                    ephemeral=True
                )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error deleting task {self.task_id}: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ {_('Error occurred while deleting task.')}",
                ephemeral=True
            )
