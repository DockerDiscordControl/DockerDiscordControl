# -*- coding: utf-8 -*-
"""
Action Logger Compatibility Layer - Maintains existing API while using new service
"""

import os
import logging
from services.infrastructure.action_log_service import get_action_log_service
from typing import Dict, Any, List

# Compatibility: Create the user_action_logger that was expected
user_action_logger = logging.getLogger('user_actions')
user_action_logger.setLevel(logging.INFO)
user_action_logger.propagate = False

# Compatibility: Export ACTION_LOG_FILE path constant
_ACTION_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs', 'action_log.json')
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
    else:
        import sys
        print(f"ERROR: Failed to get JSON logs: {result.error}", file=sys.stderr)
        return []

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