# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Module containing schedule command handlers for Discord slash commands.
These are implemented as a mixin class to be used with the main DockerControlCog.
"""
import logging
import asyncio
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands
import pytz
import time
from typing import List, Dict, Any, Optional, Union
import traceback

# Import necessary utilities
from utils.logging_utils import setup_logger
from utils.time_utils import format_datetime_with_timezone
from services.config.config_service import load_config
from services.infrastructure.action_logger import log_user_action
from services.scheduling.scheduler import (
    ScheduledTask, add_task, delete_task, update_task, load_tasks,
    get_tasks_for_container, get_next_week_tasks, get_tasks_in_timeframe,
    VALID_CYCLES, VALID_ACTIONS, DAYS_OF_WEEK,
    parse_time_string, parse_month_string, parse_weekday_string,
    CYCLE_ONCE, CYCLE_DAILY, CYCLE_WEEKLY, CYCLE_MONTHLY,
    CYCLE_NEXT_WEEK, CYCLE_NEXT_MONTH, CYCLE_CUSTOM,
    check_task_time_collision, validate_new_task_input
)

# Import translation function
from .translation_manager import _
from .control_helpers import get_guild_id, _channel_has_permission

# Import autocomplete handlers
from .autocomplete_handlers import (
    schedule_container_select, schedule_action_select, schedule_cycle_select,
    schedule_time_select, schedule_month_select, schedule_weekday_select,
    schedule_day_select, schedule_info_period_select, schedule_year_select
)

# Import helper functions
from services.scheduling.schedule_helpers import (
    parse_and_validate_time, create_and_save_task, 
    check_schedule_permissions, handle_schedule_command_error,
    create_task_success_message, ScheduleValidationError
)

# Configure logger for this module
logger = setup_logger('ddc.scheduler_commands', level=logging.DEBUG)

class ScheduleCommandsMixin:
    """
    Mixin class containing schedule command handlers for the Docker Control Cog.
    To be used with the main DockerControlCog class.
    """
    
    # Helfer-Funktion zum Umwandeln von Monatszahlen in lokalisierte Monatsnamen
    def _get_localized_month_name(self, month_int: int, language: str = "de") -> str:
        """
        Konvertiert eine Monatszahl (1-12) in einen lokalisierten Monatsnamen.
        
        Args:
            month_int: Monatszahl (1-12)
            language: Sprachcode (de, en)
            
        Returns:
            Lokalisierter Monatsname
        """
        months_de = ["Januar", "Februar", "März", "April", "Mai", "Juni", 
                    "Juli", "August", "September", "Oktober", "November", "Dezember"]
        months_en = ["January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"]
        
        if 1 <= month_int <= 12:
            if language.lower() == "de":
                return months_de[month_int - 1]
            else:
                return months_en[month_int - 1]
        return str(month_int)  # Fallback bei ungültigen Werten
    
    # --- Schedule Helper Methods ---
    async def _format_schedule_embed(self, tasks: List[ScheduledTask], title: str, description: str = "") -> discord.Embed:
        """Creates an embed with the list of scheduled tasks."""
        config = load_config()  # Performance optimization: use cache instead of load_config()
        timezone_str = config.get('timezone', 'Europe/Berlin')
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue()
        )
        
        if not tasks:
            embed.add_field(name=_("No Tasks"), value=_("No scheduled tasks were found."), inline=False)
            return embed
        
        # Sort tasks by next execution time
        tasks.sort(key=lambda t: t.next_run_ts if t.next_run_ts else float('inf'))
        
        # Limit to maximum 15 tasks for better readability
        max_tasks = min(len(tasks), 15)
        
        for i, task in enumerate(tasks[:max_tasks]):
            next_run_dt = task.get_next_run_datetime()
            if next_run_dt:
                next_run_formatted = format_datetime_with_timezone(next_run_dt, timezone_str)
                status = _("Next execution: {time}").format(time=next_run_formatted)
            else:
                status = _("No next execution time scheduled")
            
            # Cycle display
            cycle_text = task.cycle
            if task.cycle == CYCLE_WEEKLY:
                # Use either weekday_val or day_val for the weekday index
                weekday_index = None
                
                # Check for weekday_val (numeric index 0-6)
                if hasattr(task, 'weekday_val') and task.weekday_val is not None and 0 <= task.weekday_val <= 6:
                    weekday_index = task.weekday_val
                # If day_val is a string that corresponds to a weekday
                elif hasattr(task, 'day_val') and task.day_val and isinstance(task.day_val, str):
                    try:
                        day_val_lower = task.day_val.lower()
                        if day_val_lower in DAYS_OF_WEEK:
                            weekday_index = DAYS_OF_WEEK.index(day_val_lower)
                    except (ValueError, AttributeError):
                        pass
                
                if weekday_index is not None:
                    weekday_name = DAYS_OF_WEEK[weekday_index].capitalize()
                    cycle_text = f"{task.cycle} ({weekday_name})"
                else:
                    cycle_text = f"{task.cycle}"
                    
            elif task.cycle == CYCLE_MONTHLY and task.day_val is not None:
                cycle_text = f"{task.cycle} (Day {task.day_val})"
            
            # Create field for each task
            field_name = f"{i+1}. {task.container_name} - {task.action}"
            field_value = f"{_('Cycle')}: {cycle_text}\n{status}\nID: `{task.task_id}`"
            embed.add_field(name=field_name, value=field_value, inline=False)
        
        # If there are more than max_tasks tasks, add a note
        if len(tasks) > max_tasks:
            embed.set_footer(text=_("Only showing the next {count} tasks. Use the Web UI to view all.").format(count=max_tasks))
        
        return embed
    
    # Common functionality for all schedule commands
    async def _create_scheduled_task(self, ctx, container_name, action, cycle, hour, minute, year=None, month=None, day=None, weekday=None):
        """Common functionality for all schedule commands."""
        try:
            # Check permissions
            config = load_config()  # Performance optimization: use cache instead of load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            # Check if the user has schedule permissions
            has_permission = False
            servers = config.get('servers', [])
            target_server = None
            
            for server in servers:
                server_name = server.get('docker_name')
                if server_name == container_name:
                    allowed_actions = server.get('allowed_actions', [])
                    if action in allowed_actions:
                        has_permission = True
                        target_server = server
                    break
            
            if not has_permission:
                await ctx.respond(_("You don't have permission to schedule tasks for '{container}'.").format(container=container_name), ephemeral=True)
                return
            
            # Create the task
            task = ScheduledTask(
                container_name=container_name,
                action=action,
                cycle=cycle,
                year=year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                weekday=weekday,
                description=f"Scheduled by {ctx.author.name} via Discord",
                created_by=ctx.author.name,
                timezone_str=timezone_str
            )
            
            # Validate and add the task
            if not task.is_valid():
                await ctx.respond(_("The task could not be created. Please check the parameters."), ephemeral=True)
                return
            
            # Calculate next run time
            next_run = task.calculate_next_run()
            if next_run is None:
                await ctx.respond(_("The task could not be scheduled because the calculated execution time is invalid."), ephemeral=True)
                return
            
            # Add the task
            if add_task(task):
                # Format next run time
                next_run_dt = task.get_next_run_datetime()
                next_run_formatted = format_datetime_with_timezone(next_run_dt, timezone_str)
                
                # Log the action
                log_user_action(
                    action_type="SCHEDULE",
                    target=f"{container_name} ({action})",
                    user=ctx.author.name,
                    source="Discord",
                    details=f"Cycle: {cycle}, Next run: {next_run_formatted}"
                )
                
                # Send confirmation message
                await ctx.respond(_("Task successfully scheduled!\n**Container:** {container}\n**Action:** {action}\n**Cycle:** {cycle}\n**Next run:** {next_run}").format(
                    container=container_name,
                    action=action,
                    cycle=cycle,
                    next_run=next_run_formatted
                ))
                return True
            else:
                await ctx.respond(_("Error adding the task. Please check the logs."), ephemeral=True)
                return False
                
        except Exception as e:
            logger.error(f"Error creating a scheduled task: {e}", exc_info=True)
            await ctx.respond(_("An error occurred: {error}").format(error=str(e)), ephemeral=True)
            return False
    
    # --- Schedule Commands ---
    # Implementation for one-time tasks
    async def _impl_schedule_once_command(self, ctx: discord.ApplicationContext, 
                              container_name: str, 
                              action: str, 
                              time: str, 
                              day: str,
                              month: str,
                              year: str):
        """Schedules a one-time task for a Docker container."""
        try:
            # Check permissions first
            has_permission, error_msg, server_conf = check_schedule_permissions(ctx, container_name, action)
            if not has_permission:
                await ctx.respond(error_msg, ephemeral=True)
                return
            
            # Parse and validate time
            try:
                hour, minute = parse_and_validate_time(time)
            except ScheduleValidationError as e:
                await ctx.respond(str(e), ephemeral=True)
                return
            
            # Parse and validate year
            try:
                year_int = int(year)
                if year_int < 2025 or year_int > 2030:
                    await ctx.respond(_("Year must be between 2025 and 2030."), ephemeral=True)
                    return
            except ValueError:
                await ctx.respond(_("Invalid year format. Please use a 4-digit year (e.g., 2025)."), ephemeral=True)
                return
            
            # Parse and validate month
            try:
                month_int = parse_month_string(month)
            except ValueError:
                await ctx.respond(_("Invalid month format. Please use MM or month name (e.g., 07 or July)."), ephemeral=True)
                return
                
            # Parse and validate day
            try:
                day_int = int(day)
                if not (1 <= day_int <= 31):
                    await ctx.respond(_("Day must be between 1 and 31."), ephemeral=True)
                    return
            except ValueError:
                await ctx.respond(_("Invalid day format. Please use a number (1-31)."), ephemeral=True)
                return
            
            # Validate the inputs using existing function
            is_valid_input, error_message = validate_new_task_input(
                container_name, action, CYCLE_ONCE, year_int, month_int, day_int, hour, minute
            )
            if not is_valid_input:
                await ctx.respond(f"{_('Error')}: {_(error_message)}", ephemeral=True)
                return
            
            # Create the task
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            task = ScheduledTask(
                container_name=container_name,
                action=action,
                cycle=CYCLE_ONCE,
                year=year_int, month=month_int, day=day_int,
                hour=hour, minute=minute,
                description="",
                created_by=str(ctx.author),
                timezone_str=timezone_str
            )

            # Create and save task using helper
            success, result = create_and_save_task(task, ctx)
            if success:
                message = create_task_success_message(task, result)
                await ctx.respond(message, ephemeral=True)
            else:
                await ctx.respond(result, ephemeral=True)
                
        except Exception as e:
            await handle_schedule_command_error(ctx, e, "schedule_once")
    
    # Implementation for daily tasks
    async def _impl_schedule_daily_command(self, ctx: discord.ApplicationContext, 
                              container_name: str, 
                              action: str, 
                              time: str):
        """Schedules a daily task for a Docker container."""
        try:
            # Check permissions first
            has_permission, error_msg, server_conf = check_schedule_permissions(ctx, container_name, action)
            if not has_permission:
                await ctx.respond(error_msg, ephemeral=True)
                return
            
            # Parse and validate time
            try:
                hour, minute = parse_and_validate_time(time)
            except ScheduleValidationError as e:
                await ctx.respond(str(e), ephemeral=True)
                return
            
            # Validate the inputs using existing function
            is_valid_input, error_message = validate_new_task_input(
                container_name, action, CYCLE_DAILY, hour=hour, minute=minute
            )
            if not is_valid_input:
                await ctx.respond(f"{_('Error')}: {_(error_message)}", ephemeral=True)
                return
            
            # Create the task
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            task = ScheduledTask(
                container_name=container_name,
                action=action,
                cycle=CYCLE_DAILY,
                hour=hour, minute=minute,
                description="",
                created_by=str(ctx.author),
                timezone_str=timezone_str
            )

            # Create and save task using helper
            success, result = create_and_save_task(task, ctx)
            if success:
                message = create_task_success_message(task, result)
                await ctx.respond(message, ephemeral=True)
            else:
                await ctx.respond(result, ephemeral=True)
                
        except Exception as e:
            await handle_schedule_command_error(ctx, e, "schedule_daily")
    
    # Implementation for weekly tasks
    async def _impl_schedule_weekly_command(self, ctx: discord.ApplicationContext, 
                              container_name: str, 
                              action: str, 
                              time: str, 
                              weekday: str):
        """Schedules a weekly task for a Docker container."""
        try:
            # Check permissions first
            has_permission, error_msg, server_conf = check_schedule_permissions(ctx, container_name, action)
            if not has_permission:
                await ctx.respond(error_msg, ephemeral=True)
                return
            
            # Parse and validate time
            try:
                hour, minute = parse_and_validate_time(time)
            except ScheduleValidationError as e:
                await ctx.respond(str(e), ephemeral=True)
                return
            
            # Parse and validate weekday
            weekday_index = parse_weekday_string(weekday)
            if weekday_index is None:
                await ctx.respond(_("Invalid weekday format. Please use weekday name (e.g., Monday) or number (1-7)."), ephemeral=True)
                return
            
            # Get weekday name for description
            weekday_name = DAYS_OF_WEEK[weekday_index - 1] if 1 <= weekday_index <= 7 else weekday
            
            # Validate the inputs using existing function
            is_valid_input, error_message = validate_new_task_input(
                container_name, action, CYCLE_WEEKLY, weekday=weekday_index, hour=hour, minute=minute
            )
            if not is_valid_input:
                await ctx.respond(f"{_('Error')}: {_(error_message)}", ephemeral=True)
                return
            
            # Create the task
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            task = ScheduledTask(
                container_name=container_name,
                action=action,
                cycle=CYCLE_WEEKLY,
                hour=hour, 
                minute=minute, 
                weekday=weekday_index,
                day=weekday_name,
                description=_("Weekly {action} on {weekday_name} at {hour:02d}:{minute:02d}").format(
                    action=action,
                    weekday_name=weekday_name,
                    hour=hour,
                    minute=minute
                ),
                created_by=str(ctx.author),
                timezone_str=timezone_str
            )

            # Create and save task using helper
            success, result = create_and_save_task(task, ctx)
            if success:
                message = create_task_success_message(task, result)
                await ctx.respond(message, ephemeral=True)
            else:
                await ctx.respond(result, ephemeral=True)
                
        except Exception as e:
            await handle_schedule_command_error(ctx, e, "schedule_weekly")
    
    # Implementation for monthly tasks
    async def _impl_schedule_monthly_command(self, ctx: discord.ApplicationContext, 
                              container_name: str, 
                              action: str,
                              time: str,
                              day: str):
        """Schedules a monthly task for a Docker container."""
        try:
            # Check permissions first
            has_permission, error_msg, server_conf = check_schedule_permissions(ctx, container_name, action)
            if not has_permission:
                await ctx.respond(error_msg, ephemeral=True)
                return
            
            # Parse and validate time
            try:
                hour, minute = parse_and_validate_time(time)
            except ScheduleValidationError as e:
                await ctx.respond(str(e), ephemeral=True)
                return
            
            # Parse and validate day
            try:
                day_int = int(day)
                if not (1 <= day_int <= 31):
                    await ctx.respond(_("Day must be between 1 and 31."), ephemeral=True)
                    return
            except ValueError:
                await ctx.respond(_("Invalid day format. Please use a number (1-31)."), ephemeral=True)
                return
            
            # Validate the inputs using existing function
            is_valid_input, error_message = validate_new_task_input(
                container_name, action, CYCLE_MONTHLY, day=day_int, hour=hour, minute=minute
            )
            if not is_valid_input:
                await ctx.respond(f"{_('Error')}: {_(error_message)}", ephemeral=True)
                return
            
            # Create the task
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            task = ScheduledTask(
                container_name=container_name,
                action=action,
                cycle=CYCLE_MONTHLY,
                day=day_int,
                hour=hour, minute=minute,
                description="",
                created_by=str(ctx.author),
                timezone_str=timezone_str
            )

            # Create and save task using helper
            success, result = create_and_save_task(task, ctx)
            if success:
                message = create_task_success_message(task, result)
                await ctx.respond(message, ephemeral=True)
            else:
                await ctx.respond(result, ephemeral=True)
                
        except Exception as e:
            await handle_schedule_command_error(ctx, e, "schedule_monthly")
    
    # Implementation for schedule command (help)
    async def _impl_schedule_command(self, ctx: discord.ApplicationContext):
        """Shows help for the various scheduling commands."""
        # Check channel permissions (also for the help command)
        if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond(_("This command can only be used in server channels."), ephemeral=True)
            return
            
        config = self.config
        if not _channel_has_permission(ctx.channel.id, 'schedule', config):
            await ctx.respond(_("You do not have permission to use schedule commands in this channel."), ephemeral=True)
            return
                
        embed = discord.Embed(
            title=_("DockerDiscordControl - Task Scheduling"),
            description=_("Task scheduling is now handled through UI buttons in container status messages:"),
            color=discord.Color.blue()
        )
        embed.add_field(name=_("⏰ Add Tasks"), value=_("Click the ⏰ button in any container status message to schedule tasks (once, daily, weekly, monthly, yearly)."), inline=False)
        embed.add_field(name=_("❌ Manage Tasks"), value=_("Click the ❌ button to view and delete scheduled tasks for that container."), inline=False)
        embed.add_field(name=_("Available Task Types"), value=_("**One-time**, **Daily**, **Weekly**, **Monthly**, and **Yearly** tasks are supported through the UI."), inline=False)
        
        embed.add_field(name=_("How to Access"), 
                        value=_("Use `/serverstatus` or `/ss` to see container status messages, then click the ⏰ or ❌ buttons to manage tasks."), 
                        inline=False)
        
        await ctx.respond(embed=embed)
    
    # Implementation for schedule_info command
    async def _impl_schedule_info_command(self, ctx: discord.ApplicationContext,
                                  container_name: str = "all",
                                  period: str = "all"):
        """Shows information about scheduled tasks."""
        try:
            # Defer immediately to prevent timeout - even before other checks
            await ctx.defer()
        except Exception as defer_error:
            logger.error(f"Failed to defer task_info interaction: {defer_error}")
            # Try to respond with error if defer failed
            try:
                await ctx.respond(_("Command timeout. Please try again."), ephemeral=True)
            except:
                pass
            return
        
        try:
            # Check channel permissions
            if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
                await ctx.followup.send(_("This command can only be used in server channels."), ephemeral=True)
                return
            
            config = self.config
            if not _channel_has_permission(ctx.channel.id, 'schedule', self.config):
                await ctx.followup.send(_("This channel does not have permission to use this command."), ephemeral=True)
                return

            # Get all existing tasks
            all_tasks = load_tasks()
            logger.info(f"Total tasks found: {len(all_tasks)}")
            if not all_tasks:
                await ctx.followup.send(_("No scheduled tasks found."))
                return

            now = datetime.now(pytz.timezone(config.get('timezone', 'Europe/Berlin')))
            current_time = time.time()
            tasks_to_update = []  # List for tasks that need to be updated
            active_tasks_count = 0
            
            # Filter tasks by container name if specified
            filtered_tasks = []
            for task in all_tasks:
                logger.debug(f"Checking task {task.task_id}: container={task.container_name}, action={task.action}, " + 
                         f"cycle={task.cycle}, active={task.is_active}, status={task.status}, " + 
                         f"next_run_ts={task.next_run_ts}")
                
                # Count active tasks
                if task.is_active and (task.next_run_ts is None or task.next_run_ts >= current_time):
                    active_tasks_count += 1
                
                # Skip if the task has no next_run_ts and is a one-time task (expired)
                if task.cycle == CYCLE_ONCE and task.next_run_ts is None:
                    logger.debug(f"Task {task.task_id} is skipped: CYCLE_ONCE without next_run_ts")
                    # If the task is still active, deactivate and mark for update
                    if task.is_active:
                        task.is_active = False
                        tasks_to_update.append(task)
                        logger.info(f"Task {task.task_id} has expired (no next_run_ts) and will be deactivated")
                    continue  # Don't display

                # Skip if the task is a completed one-time task
                if task.cycle == CYCLE_ONCE and task.status == "completed":
                    logger.debug(f"Task {task.task_id} is skipped: CYCLE_ONCE with status=completed")
                    # If the task is still active, deactivate and mark for update
                    if task.is_active:
                        task.is_active = False
                        tasks_to_update.append(task)
                        logger.info(f"Task {task.task_id} has expired (status completed) and will be deactivated")
                    continue  # Don't display
                
                # Skip if the task is a one-time task and its execution time is in the past
                if task.cycle == CYCLE_ONCE and task.next_run_ts and task.next_run_ts < current_time:
                    logger.debug(f"Task {task.task_id} is skipped: CYCLE_ONCE with next_run_ts in the past ({task.next_run_ts} < {current_time})")
                    # If the task is still active, deactivate and mark for update
                    if task.is_active:
                        task.is_active = False
                        tasks_to_update.append(task)
                        logger.info(f"Task {task.task_id} has expired (time in the past) and will be deactivated")
                    continue  # Don't display

                # Skip inactive tasks
                if not task.is_active:
                    logger.debug(f"Task {task.task_id} is skipped: not active")
                    continue  # Don't display inactive tasks

                # Apply container filter
                if container_name != "all" and task.container_name != container_name:
                    logger.debug(f"Task {task.task_id} is skipped: Container filter ({container_name} != {task.container_name})")
                    continue
                
                logger.debug(f"Task {task.task_id} is added to filtered list")
                filtered_tasks.append(task)

            logger.info(f"After initial filtering, remaining tasks: {len(filtered_tasks)}, total active tasks: {active_tasks_count}")

            # Save changes to deactivated tasks
            if tasks_to_update:
                for task in tasks_to_update:
                    update_task(task)
                    logger.info(f"Task {task.task_id} has been marked as expired and deactivated. Changes saved.")

            # Important: Check again if there are still tasks left
            if not filtered_tasks:
                # If no tasks were found, check if we deactivated any tasks
                if tasks_to_update:
                    await ctx.respond(_("All tasks have been marked as expired or inactive."))
                else:
                    await ctx.respond(_("No active scheduled tasks found for the specified criteria."))
                return
            
            if period != "all":
                before_period_filter = len(filtered_tasks)
                period_filtered_tasks = []
                
                if period == "next_day":
                    # Next 24 hours
                    start_time = time.time()
                    end_time = (now + timedelta(days=1)).timestamp()
                    
                    for task in filtered_tasks:
                        if task.next_run_ts and start_time <= task.next_run_ts <= end_time:
                            period_filtered_tasks.append(task)
                    
                    filtered_tasks = period_filtered_tasks
                    title = _("Scheduled tasks for the next 24 hours")
                
                elif period == "next_week":
                    # Next week
                    start_time = time.time()
                    end_time = (now + timedelta(days=7)).timestamp()
                    
                    for task in filtered_tasks:
                        if task.next_run_ts and start_time <= task.next_run_ts <= end_time:
                            period_filtered_tasks.append(task)
                    
                    filtered_tasks = period_filtered_tasks
                    title = _("Scheduled tasks for the next week")
                    
                elif period == "next_month":
                    # Next month
                    start_time = time.time()
                    end_time = (now + timedelta(days=30)).timestamp()
                    
                    for task in filtered_tasks:
                        if task.next_run_ts and start_time <= task.next_run_ts <= end_time:
                            period_filtered_tasks.append(task)
                    
                    filtered_tasks = period_filtered_tasks
                    title = _("Scheduled tasks for the next month")
                    
                else:
                    title = _("All active scheduled tasks")
                
                logger.info(f"After period filtering, remaining tasks: {len(filtered_tasks)} (before filter: {before_period_filter})")
            else:
                title = _("All active scheduled tasks")
            
            if not filtered_tasks:
                await ctx.followup.send(_("No active scheduled tasks found for the specified period."))
                return
                
            embed = await self._format_schedule_embed(filtered_tasks, title)
            await ctx.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error executing schedule_info command: {e}")
            logger.error(traceback.format_exc())
            try:
                await ctx.followup.send(_("An error occurred while fetching scheduled tasks. Please check the logs."))
            except:
                pass  # Interaction might already be dead

    # Implementation for yearly tasks
    async def _impl_schedule_yearly_command(self, ctx: discord.ApplicationContext, 
                              container_name: str, 
                              action: str, 
                              time: str,
                              month: str,
                              day: str):
        """Schedules a yearly task for a Docker container."""
        try:
            # Check permissions first
            has_permission, error_msg, server_conf = check_schedule_permissions(ctx, container_name, action)
            if not has_permission:
                await ctx.respond(error_msg, ephemeral=True)
                return
            
            # Parse and validate time
            try:
                hour, minute = parse_and_validate_time(time)
            except ScheduleValidationError as e:
                await ctx.respond(str(e), ephemeral=True)
                return
            
            # Parse and validate month
            try:
                month_int = parse_month_string(month)
            except ValueError:
                await ctx.respond(_("Invalid month format. Please use MM or month name (e.g., 07 or July)."), ephemeral=True)
                return
                
            # Parse and validate day
            try:
                day_int = int(day)
                if not (1 <= day_int <= 31):
                    await ctx.respond(_("Day must be between 1 and 31."), ephemeral=True)
                    return
            except ValueError:
                await ctx.respond(_("Invalid day format. Please use a number (1-31)."), ephemeral=True)
                return
            
            # Use current year for yearly tasks
            current_year = datetime.now(timezone.utc).year
            
            # Validate the inputs using existing function
            is_valid_input, error_message = validate_new_task_input(
                container_name, action, "yearly", year=current_year, month=month_int, day=day_int, hour=hour, minute=minute
            )
            if not is_valid_input:
                await ctx.respond(f"{_('Error')}: {_(error_message)}", ephemeral=True)
                return
            
            # Create the task
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            task = ScheduledTask(
                container_name=container_name,
                action=action,
                cycle="yearly",
                year=current_year, month=month_int, day=day_int,
                hour=hour, minute=minute,
                description="",
                created_by=str(ctx.author),
                timezone_str=timezone_str
            )

            # Create and save task using helper
            success, result = create_and_save_task(task, ctx)
            if success:
                message = create_task_success_message(task, result)
                await ctx.respond(message, ephemeral=True)
            else:
                await ctx.respond(result, ephemeral=True)
                
        except Exception as e:
            await handle_schedule_command_error(ctx, e, "schedule_yearly") 