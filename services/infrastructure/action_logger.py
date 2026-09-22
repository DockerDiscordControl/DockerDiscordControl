# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Action Logger Compatibility Layer - Maintains existing API while using new service
"""

import logging
from pathlib import Path
from services.infrastructure.action_log_service import get_action_log_service, DEFAULT_TEXT_LOG_FILE
from typing import Dict, Any, List

logger = logging.getLogger('ddc.action_logger')


class ActionLogUnreadable(RuntimeError):
    """The action log exists as a question but could not be answered.

    A subclass of RuntimeError so the handlers already in the path catch it:
    ContainerLogService turns it into a failed LogResult and the route answers
    an error instead of a clean, empty history (review D5).
    """


# Compatibility: Create the user_action_logger that was expected
user_action_logger = logging.getLogger('user_actions')
user_action_logger.setLevel(logging.INFO)
user_action_logger.propagate = False

# Compatibility: Export ACTION_LOG_FILE path constant - the file ActionLogService
# writes. This named logs/action_log.json on its own, a file nothing writes, so the
# panel's download button and /action-log answered "not found" (review A3).
_ACTION_LOG_FILE = str(DEFAULT_TEXT_LOG_FILE)

ACTION_LOG_FILE = _ACTION_LOG_FILE  # Both names for compatibility

def log_user_action(action: str, target: str, user: str = "System",
                   source: str = "Unknown", details: str = "-"):
    """
    Log user actions - compatibility function for existing code.

    Args:
        action: The action being performed (e.g., START, STOP, RESTART)
        target: The target of the action (e.g., container name)
        user: The user who initiated the action
        source: Source of the action (e.g., Web UI, Discord Command)
        details: Additional details about the action
    """
    service = get_action_log_service()
    result = service.log_action(action, target, user, source, details)

    if not result.success:
        import sys
        print(f"ERROR: Failed to log action: {result.error}", file=sys.stderr)

def get_action_logs_json(limit: int = 500) -> List[Dict[str, Any]]:
    """
    Retrieve action logs from JSON file - compatibility function.

    Args:
        limit: Maximum number of entries to return (default: 500)

    Returns:
        List of action log entries, newest first
    """
    service = get_action_log_service()
    result = service.get_logs(limit=limit, format="json")

    if result.success:
        return [entry.to_dict() for entry in result.data]

    # Not an empty list. That is what this returns when there genuinely are no
    # entries, and the two must not look the same: the caller wrapped the empty
    # list in success=True and the panel showed a clean, empty history for a log
    # that could not be read at all. The sibling get_action_logs_text has always
    # returned an error string on this path (review D5). The reason also went to
    # stderr instead of the log the operator reads.
    logger.error(f"Action log could not be read: {result.error}")
    raise ActionLogUnreadable(f"Action log could not be read: {result.error}")

def get_action_logs_text(limit: int = 500) -> str:
    """
    Retrieve action logs as formatted text - compatibility function.

    Args:
        limit: Maximum number of entries to return (default: 500)

    Returns:
        Formatted log text
    """
    service = get_action_log_service()
    result = service.get_logs(limit=limit, format="text")

    if result.success:
        return result.data
    else:
        import sys
        print(f"ERROR: Failed to get text logs: {result.error}", file=sys.stderr)
        return "Error loading action logs"
