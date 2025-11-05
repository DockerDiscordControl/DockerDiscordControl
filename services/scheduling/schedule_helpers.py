# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Schedule Helpers                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
Utility functions for schedule commands to eliminate redundancy.
Contains common validation, error handling, and task creation logic.
"""

from typing import Tuple, Optional
import discord
import pytz

from .scheduler import (
    ScheduledTask, add_task, check_task_time_collision,
    parse_time_string, validate_new_task_input
)
from services.infrastructure.action_logger import log_user_action
from cogs.translation_manager import _
from utils.logging_utils import get_module_logger
from utils.time_utils import get_datetime_imports

# Zentrale datetime-Imports
datetime, timedelta, timezone, time = get_datetime_imports()

# Logger mit zentraler Utility
logger = get_module_logger('schedule_helpers')

class ScheduleValidationError(Exception):
    """Custom exception for schedule validation errors."""
    pass

def parse_and_validate_time(time_str: str) -> Tuple[int, int]:
    """
    Parses and validates time string.
    
    Args:
        time_str: Time in HH:MM format
        
    Returns:
        Tuple of (hour, minute)
        
    Raises:
        ScheduleValidationError: If time format is invalid
    """
    try:
        hour, minute = parse_time_string(time_str)
        return hour, minute
    except ValueError as e:
        raise ScheduleValidationError(_("Invalid time format. Please use HH:MM (e.g., 14:30)."))

def validate_task_before_creation(task: ScheduledTask) -> None:
    """
    Validates a task before creation with comprehensive checks.
    
    Args:
        task: The ScheduledTask to validate
        
    Raises:
        ScheduleValidationError: If validation fails
    """
    if not task.is_valid() or task.next_run_ts is None:
        raise ScheduleValidationError(_("Cannot schedule task: The calculated execution time is invalid (e.g., in the past)."))
    
    if check_task_time_collision(task.container_name, task.next_run_ts):
        raise ScheduleValidationError(_("Cannot schedule task: It conflicts with an existing task for container '{container}' within a 10-minute window.").format(container=task.container_name))

def create_and_save_task(task: ScheduledTask, ctx: discord.ApplicationContext) -> Tuple[bool, str]:
    """
    Creates and saves a task with proper error handling and logging.
    
    Args:
        task: The ScheduledTask to save
        ctx: Discord ApplicationContext for user info
        
    Returns:
        Tuple of (success, message)
    """
    try:
        validate_task_before_creation(task)
        
        if add_task(task):
            # Get timezone for formatting
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            # Format next run time
            next_run_formatted = datetime.fromtimestamp(
                task.next_run_ts, 
                pytz.timezone(timezone_str)
            ).strftime('%Y-%m-%d %H:%M %Z%z')
            
            # Log the action
            log_user_action(
                action="SCHEDULE_CREATE_CMD", 
                target=f"{task.container_name} ({task.action})", 
                user=str(ctx.author),
                source="Discord Command",
                details=f"Cycle: {task.cycle}, Next run: {next_run_formatted}"
            )
            
            return True, next_run_formatted
        else:
            return False, _("Failed to schedule task. It might conflict with an existing task or another error occurred.")
            
    except ScheduleValidationError as e:
        return False, str(e)
    except Exception as e:
        logger.error(f"Unexpected error creating task: {e}", exc_info=True)
        return False, _("An unexpected error occurred while creating the task.")

def check_schedule_permissions(ctx: discord.ApplicationContext, container_name: str, action: str) -> Tuple[bool, Optional[str], Optional[dict]]:
    """
    Checks if user has permission to schedule tasks for a container.
    
    Args:
        ctx: Discord ApplicationContext
        container_name: Name of the container
        action: Action to perform
        
    Returns:
        Tuple of (has_permission, error_message, server_config)
    """
    config = load_config()
    # SERVICE FIRST: Use ServerConfigService instead of direct config access
    server_config_service = get_server_config_service()
    servers = server_config_service.get_all_servers()
    
    for server in servers:
        if server.get('docker_name') == container_name:
            allowed_actions = server.get('allowed_actions', [])
            if action in allowed_actions:
                return True, None, server
            else:
                return False, _("You don't have permission to perform '{action}' on '{container}'.").format(
                    action=action, container=container_name
                ), server
    
    return False, _("Container '{container}' not found in configuration.").format(container=container_name), None

async def handle_schedule_command_error(ctx: discord.ApplicationContext, error: Exception, command_name: str) -> None:
    """
    Handles errors in schedule commands with consistent logging and user feedback.
    
    Args:
        ctx: Discord ApplicationContext
        error: The exception that occurred
        command_name: Name of the command for logging
    """
    logger.error(f"Error executing {command_name} command: {error}", exc_info=True)
    await ctx.respond(_("An error occurred: {error}").format(error=str(error)), ephemeral=True)

def create_task_success_message(task: ScheduledTask, next_run_formatted: str) -> str:
    """
    Creates a standardized success message for task creation.
    
    Args:
        task: The created task
        next_run_formatted: Formatted next run time
        
    Returns:
        Success message string
    """
    if task.cycle == "once":
        return _("Task for {container_name} scheduled for {next_run_formatted}.").format(
            container_name=task.container_name, 
            next_run_formatted=next_run_formatted
        )
    elif task.cycle == "daily":
        # Extract hour and minute from time_str
        try:
            hour, minute = map(int, task.time_str.split(':'))
            return _("Task for {container_name} scheduled daily at {hour:02d}:{minute:02d}.").format(
                container_name=task.container_name, 
                hour=hour, 
                minute=minute
            )
        except (ValueError, AttributeError):
            return _("Task for {container_name} scheduled daily.").format(container_name=task.container_name)
    elif task.cycle == "weekly":
        # Use day_val for weekday name, fallback to weekday_val
        weekday_name = "Unknown"
        if hasattr(task, 'day_val') and task.day_val:
            weekday_name = str(task.day_val)
        elif hasattr(task, 'weekday_val') and task.weekday_val is not None:
            # Convert weekday_val (0-6) to weekday name
            from services.scheduling.scheduler import DAYS_OF_WEEK
            if 0 <= task.weekday_val <= 6:
                weekday_name = DAYS_OF_WEEK[task.weekday_val].capitalize()
        
        try:
            hour, minute = map(int, task.time_str.split(':'))
            return _("Task for {container_name} scheduled weekly on {weekday} at {hour:02d}:{minute:02d}.").format(
                container_name=task.container_name,
                weekday=weekday_name,
                hour=hour,
                minute=minute
            )
        except (ValueError, AttributeError):
            return _("Task for {container_name} scheduled weekly on {weekday}.").format(
                container_name=task.container_name,
                weekday=weekday_name
            )
    elif task.cycle == "monthly":
        # Use day_val for day of month
        day = getattr(task, 'day_val', 'Unknown')
        try:
            hour, minute = map(int, task.time_str.split(':'))
            return _("Task for {container_name} scheduled monthly on day {day} at {hour:02d}:{minute:02d}.").format(
                container_name=task.container_name,
                day=day,
                hour=hour,
                minute=minute
            )
        except (ValueError, AttributeError):
            return _("Task for {container_name} scheduled monthly on day {day}.").format(
                container_name=task.container_name,
                day=day
            )
    elif task.cycle == "yearly":
        # Use month_val and day_val for yearly tasks
        month = getattr(task, 'month_val', 'Unknown')
        day = getattr(task, 'day_val', 'Unknown')
        try:
            hour, minute = map(int, task.time_str.split(':'))
            return _("Task for {container_name} scheduled yearly on {month}/{day} at {hour:02d}:{minute:02d}.").format(
                container_name=task.container_name,
                month=month,
                day=day,
                hour=hour,
                minute=minute
            )
        except (ValueError, AttributeError):
            return _("Task for {container_name} scheduled yearly on {month}/{day}.").format(
                container_name=task.container_name,
                month=month,
                day=day
            )
    else:
        return _("Task for {container_name} scheduled successfully.").format(container_name=task.container_name) 