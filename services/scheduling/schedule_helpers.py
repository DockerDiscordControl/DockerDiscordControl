# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Schedule Helpers                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Utility functions for schedule commands to eliminate redundancy.
Contains common validation, error handling, and task creation logic.
"""

from typing import Tuple, Optional
import discord
import pytz
import docker

from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service

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

# Five helpers stood here: parse_and_validate_time, create_and_save_task,
# check_schedule_permissions, handle_schedule_command_error and
# create_task_success_message. They served cogs/scheduler_commands.py, the
# slash commands removed in review B17, and nothing called them afterwards.
# check_schedule_permissions is why they had to go rather than stay: it is
# named like a permission check and only reads the container's
# allowed_actions - it never looks at the channel, so the next caller would
# have got a guard that guards nothing (review C2). The live path asks
# properly: the task buttons require the channel's schedule permission or a
# registered admin (SPEC.md Z5, B2).


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
