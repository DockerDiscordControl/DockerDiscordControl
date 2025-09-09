# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Module containing autocomplete handlers for Discord slash commands.
These functions provide dropdown suggestions for command arguments.
"""
import logging
import discord
from datetime import datetime, timezone
from typing import List, Dict, Union, Optional, Callable, Any
from functools import lru_cache
import time

# Import app_commands using central utility
from utils.app_commands_helper import get_app_commands
app_commands = get_app_commands()

# Import utility functions
from services.config.config_service import load_config
from utils.logging_utils import setup_logger
from services.scheduling.scheduler import (
    VALID_CYCLES, VALID_ACTIONS, DAYS_OF_WEEK,
    parse_time_string, parse_month_string, parse_weekday_string
)

# Configure logger for this module
logger = setup_logger('ddc.autocomplete_handlers', level=logging.DEBUG)

# --- Custom Cache for schedule_container_select ---
_schedule_container_cache = None
_schedule_container_cache_timestamp = 0
_SCHEDULE_CONTAINER_CACHE_TTL = 60

# --- Container Selection Autocomplete ---
async def schedule_container_select(
    ctx: discord.AutocompleteContext # Explicitly AutocompleteContext for PyCord
):
    """Autocomplete function for container names in schedule command.
    Always returns a simple list of strings to avoid serialization issues.
    Uses a custom cache to reduce load.
    """
    global _schedule_container_cache, _schedule_container_cache_timestamp
    value_being_typed = ctx.value
    current_time = time.time()

    # Check cache
    if _schedule_container_cache is not None and (current_time - _schedule_container_cache_timestamp < _SCHEDULE_CONTAINER_CACHE_TTL):
        logger.debug(f"schedule_container_select: Using cached data. Input: '{value_being_typed}'")
        # Filter cached choices based on current input
        return _filter_choices(value_being_typed, _schedule_container_cache)

    logger.debug(f"schedule_container_select: Cache miss or expired. Refreshing. Input: '{value_being_typed}'")
    
    servers = get_cached_servers()  # Performance optimization: use cache instead of load_config()
    choices_to_cache = [] # This list will be cached
    
    active_docker_data_set = set() # Stores (docker_name, is_running)
    try:
        from services.docker_service.docker_utils import get_containers_data
        containers_data = await get_containers_data() # This has its own 10s cache
        
        if containers_data:
            for container_data in containers_data:
                docker_name = container_data.get('name')
                if docker_name:
                    # is_running = container_data.get('running', False) # Status not directly used for choice generation here
                    active_docker_data_set.add(docker_name) # Store only names for matching
            logger.debug(f"Found {len(active_docker_data_set)} active container names via Docker API/utils cache")
        else:
            logger.debug("No active container names found via Docker API/utils cache")
            
    except Exception as e:
        logger.error(f"Error accessing Docker API or its cache in schedule_container_select: {e}")
        # Fallback to docker_status_cache from cogs.docker_control if direct/util-cached query fails
        try:
            from cogs.docker_control import docker_status_cache
            logger.debug("Falling back to docker_status_cache for active container names")
            for docker_name_cached, container_item in docker_status_cache.items():
                if docker_name_cached and container_item and isinstance(container_item, dict) and 'data' in container_item:
                    # Assuming docker_status_cache stores names directly or can be adapted
                    active_docker_data_set.add(docker_name_cached)
        except Exception as cache_e:
            logger.error(f"Error accessing docker_status_cache: {cache_e}")

    # Populate choices_to_cache from configured servers
    # We present all configured servers, their actual current status (running/stopped)
    # from get_containers_data or the fallback cache is primarily for display elsewhere,
    # not strictly for filtering the list of *schedulable* containers in autocomplete.
    # The main goal here is to list containers that *can* be scheduled.
    for server in servers:
        docker_name = server.get('docker_name')
        # display_name = server.get('name', docker_name) # Not directly used for filtering value_being_typed against display_name here
        
        if docker_name:
            choices_to_cache.append(docker_name)
            # Optionally, could add display_name if filtering logic were to change to also match display_name:
            # choices_to_cache.append(display_name) # But ensure _filter_choices handles this or adapt

    # Update cache
    _schedule_container_cache = sorted(list(set(choices_to_cache))) # Ensure uniqueness and sort
    _schedule_container_cache_timestamp = current_time
    
    logger.debug(f"schedule_container_select: Refreshed cache. Returning filtered choices. Input: '{value_being_typed}'")
    return _filter_choices(value_being_typed, _schedule_container_cache)

# --- General Filtering Function ---
def _filter_choices(value_being_typed: str, choices_list: List[str]) -> List[str]:
    """Helper function to filter choices based on user input"""
    if not value_being_typed:
        return choices_list[:25]  # Discord limit
    return [choice for choice in choices_list if value_being_typed.lower() in choice.lower()][:25]

# --- Action Selection Autocomplete ---
async def schedule_action_select(
    ctx: discord.AutocompleteContext 
):
    """Autocomplete function for actions in schedule command.
    Always returns a simple list of strings with valid container actions (start, stop, restart).
    """
    value_being_typed = ctx.value # What user is typing for the action
    
    logger.debug(f"schedule_action_select: value_being_typed='{value_being_typed}' for action.")

    # Use VALID_ACTIONS from scheduler which are 'start', 'stop', 'restart'
    # These are generally the only actions one would schedule.
    allowed_actions_for_scheduling = list(VALID_ACTIONS) 
    
    return _filter_choices(value_being_typed, allowed_actions_for_scheduling)

# --- Cycle Selection Autocomplete ---
async def schedule_cycle_select(
    ctx: discord.AutocompleteContext
):
    value_being_typed = ctx.value
    return _filter_choices(value_being_typed, VALID_CYCLES)

# --- Time Suggestions Cache ---
@lru_cache(maxsize=1)
def _get_time_suggestions():
    """Cache time suggestions to avoid recreating them on every autocomplete request"""
    suggestions = []
    
    # Add standard times in 1-hour intervals (00:00 to 23:00)
    for h in range(24):
        suggestions.append(f"{h:02d}:00")
    
    # Add commonly used times in 15-minute intervals
    for h in range(24):
        for m in (15, 30, 45):
            suggestions.append(f"{h:02d}:{m:02d}")
    
    # Sort the list for consistent display
    suggestions.sort()
    return suggestions

# --- Time Selection Autocomplete ---
async def schedule_time_select(
    ctx: discord.AutocompleteContext
):
    value_being_typed = ctx.value
    
    # Get cached time suggestions
    suggestions_24h = _get_time_suggestions()
    
    if not value_being_typed:
        # If no input, show standard time options in 1-hour intervals to reduce flooding
        return [time_s for time_s in suggestions_24h if time_s.endswith(":00")]
    
    # Check if the input is in HH:MM format or at least partially
    if ":" in value_being_typed:
        hour_part, minute_part = value_being_typed.split(":", 1)
        
        # If hour and minute were provided but still incomplete
        if hour_part.strip() and len(hour_part.strip()) <= 2:
            try:
                hour_int = int(hour_part.strip())
                if 0 <= hour_int < 24:
                    # If the hour is valid, show matching minutes
                    if not minute_part.strip():
                        # If no minute is specified, show all options for this hour
                        return [f"{hour_int:02d}:{m:02d}" for m in (0, 15, 30, 45)]
                    else:
                        # If minute is partially specified, filter by matching minutes
                        minute_choices = []
                        for m in (0, 15, 30, 45):
                            if str(m).startswith(minute_part.strip()) or f"{m:02d}".startswith(minute_part.strip()):
                                minute_choices.append(f"{hour_int:02d}:{m:02d}")
                        return minute_choices
            except ValueError:
                pass # Fall through to general filtering
    
    # General text filtering if specific filtering not applicable
    return _filter_choices(value_being_typed, suggestions_24h)

# --- Month Selection Autocomplete ---
async def schedule_month_select(
    ctx: discord.AutocompleteContext
):
    value_being_typed = ctx.value
    
    # Import the translation function
    from .translation_manager import _
    
    # Get the current language from config
    config = load_config()  # Performance optimization: use cache instead of load_config()
    current_language = config.get('language', 'en')
    
    # English month names
    month_names = ["January", "February", "March", "April", "May", "June", 
                 "July", "August", "September", "October", "November", "December"]
    
    # Build display map with translations if not English
    month_map_display = {}
    for i, name in enumerate(month_names):
        month_num = f"{i+1:02d}"
        
        # Get translated month name
        translated_name = _(name)
        
        # Use translated name if available, otherwise use English
        display_name = translated_name if translated_name != name else name
        month_map_display[month_num] = f"{month_num} - {display_name}"
    
    choices = []
    for val, name in month_map_display.items():
        if not value_being_typed or value_being_typed.lower() in name.lower() or value_being_typed == val:
            # Return value directly instead of app_commands.Choice
            choices.append(val)
    
    # Add pure numeric typing support
    if value_being_typed and value_being_typed.isdigit():
        num_val = f"{int(value_being_typed):02d}"
        if "01" <= num_val <= "12" and num_val not in choices:
            choices.append(num_val)

    # Sort by value
    choices.sort()
    return choices[:25]

# --- Weekday Selection Autocomplete ---
async def schedule_weekday_select(
    ctx: discord.AutocompleteContext
):
    value_being_typed = ctx.value
    
    # Import the translation function
    from .translation_manager import _
    
    # Standard English weekday names
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # Get translated choices based on both English and translated matching
    choices = []
    for day in weekdays:
        # Get translated version
        translated_day = _(day)
        
        # Add to choices if input matches either English or translated version
        if (not value_being_typed or 
            value_being_typed.lower() in day.lower() or 
            value_being_typed.lower() in translated_day.lower()):
            choices.append(day)  # Always use English values for consistency
    
    return choices[:25]

# --- Day of Month Cache ---
@lru_cache(maxsize=1)
def _get_days_of_month():
    """Cache days of month to avoid recreating on each autocomplete request"""
    return [f"{d:02d}" for d in range(1, 32)]

# --- Day of Month Selection Autocomplete ---
async def schedule_day_select(
    ctx: discord.AutocompleteContext
):
    value_being_typed = ctx.value
    
    # Get cached days
    days_str = _get_days_of_month()
    
    # The input is the text entered by the user (or empty)
    if not value_being_typed:
        # When input is empty, show the strategically selected days
        # Exactly 24 days (below Discord's limit of 25 options)
        return ["01", "02", "03", "04", "05", "07", "09", "10", "12", "13", "14", "15", 
                "17", "18", "20", "21", "22", "24", "25", "26", "27", "28", "30", "31"]
    
    # Prepare the entered value for filtering
    value_being_typed = value_being_typed.strip()
    
    # If the user entered a single digit number
    if value_being_typed.isdigit() and len(value_being_typed) == 1:
        # For single-digit inputs, show two-digit options that start with this digit
        filtered_days = [day for day in days_str if day.startswith(value_being_typed)]
        return filtered_days[:25]
    
    # Check for exact match
    if value_being_typed in days_str or value_being_typed.lstrip('0') in [d.lstrip('0') for d in days_str]:
        exact_day = next((d for d in days_str if d.lstrip('0') == value_being_typed.lstrip('0')), None)
        if exact_day:
            return [exact_day] + [d for d in days_str if d != exact_day and value_being_typed in d][:24]
    
    # General filtering
    filtered_days = _filter_choices(value_being_typed, days_str)
    return filtered_days

# --- Period Selection for Schedule Info Command ---
async def schedule_info_period_select(
    ctx: discord.AutocompleteContext
):
    value_being_typed = ctx.value
    
    # Import the translation function
    from .translation_manager import _
    
    # Standard period values
    periods = ["all", "next_week", "next_month", "today", "tomorrow"]
    
    # Get translated choices based on both English and translated matching
    choices = []
    for period in periods:
        # Get translated version
        translated_period = _(period)
        
        # Add to choices if input matches either English or translated version
        if (not value_being_typed or 
            value_being_typed.lower() in period.lower() or 
            value_being_typed.lower() in translated_period.lower()):
            choices.append(period)  # Always use English values for consistency
    
    return choices[:25]

# --- Year Selection Autocomplete ---
async def schedule_year_select(
    ctx: discord.AutocompleteContext
):
    value_being_typed = ctx.value
    current_year = datetime.now(timezone.utc).year
    years_str = [str(current_year + i) for i in range(6)] 
    
    return _filter_choices(value_being_typed, years_str)

# --- Task ID Selection Autocomplete for Schedule Delete ---
async def schedule_task_id_select(
    ctx: discord.AutocompleteContext
):
    """Autocomplete function for task IDs in schedule_delete command.
    Shows active scheduled tasks with format: 'task_id - container (action, cycle)'
    """
    value_being_typed = ctx.value
    
    try:
        from services.scheduling.scheduler import load_tasks, CYCLE_ONCE
        import time
        
        # Load all tasks
        all_tasks = load_tasks()
        if not all_tasks:
            return []
        
        # Filter to only active tasks
        current_time = time.time()
        active_tasks = []
        
        for task in all_tasks:
            # Skip inactive tasks
            if not task.is_active:
                continue
                
            # Skip expired one-time tasks
            if task.cycle == CYCLE_ONCE:
                if task.next_run_ts is None or task.next_run_ts < current_time:
                    continue
                if getattr(task, 'status', None) == "completed":
                    continue
            
            active_tasks.append(task)
        
        # Create choices in format: task_id - container (action, cycle)
        choices = []
        for task in active_tasks[:25]:  # Discord limit
            try:
                # Create display format
                display_name = f"{task.task_id} - {task.container_name} ({task.action}, {task.cycle})"
                
                # For autocomplete, we return the task_id as value but show the descriptive format
                # Check if user input matches task_id or any part of the display
                if (not value_being_typed or 
                    value_being_typed.lower() in task.task_id.lower() or
                    value_being_typed.lower() in display_name.lower()):
                    choices.append(task.task_id)
                    
            except Exception as e:
                logger.debug(f"Error formatting task {task.task_id}: {e}")
                continue
        
        return choices[:25]
        
    except Exception as e:
        logger.error(f"Error in schedule_task_id_select: {e}")
        return [] 