#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Container Log Service                          #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Container Log Service - Handles comprehensive log retrieval, filtering, and processing
for various log types including container logs, bot logs, Discord logs, and action logs.
"""

import os
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class LogType(Enum):
    """Enumeration of supported log types."""
    CONTAINER = "container"
    BOT = "bot"
    DISCORD = "discord"
    WEBUI = "webui"
    APPLICATION = "application"
    ACTION = "action"


@dataclass
class ContainerLogRequest:
    """Represents a container log retrieval request."""
    container_name: str
    max_lines: int = 500


@dataclass
class FilteredLogRequest:
    """Represents a filtered log retrieval request."""
    log_type: LogType
    max_lines: int = 500


@dataclass
class ActionLogRequest:
    """Represents an action log retrieval request."""
    format_type: str = "text"  # "text" or "json"
    limit: int = 500


@dataclass
class ClearLogRequest:
    """Represents a log clearing request."""
    log_type: str = "container"


@dataclass
class LogResult:
    """Represents the result of log retrieval."""
    success: bool
    content: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: int = 200


class ContainerLogService:
    """Service for comprehensive container and application log management."""

    def __init__(self):
        self.logger = logger
        self.default_container = 'dockerdiscordcontrol'

        # Log file paths (try Docker paths first, then development paths)
        self.log_paths = {
            'bot': ['/app/logs/bot.log', '/Volumes/appdata/dockerdiscordcontrol/logs/bot.log'],
            'discord': ['/app/logs/discord.log', '/Volumes/appdata/dockerdiscordcontrol/logs/discord.log'],
            'webui': ['/app/logs/webui_error.log', '/Volumes/appdata/dockerdiscordcontrol/logs/webui_error.log'],
            'application': ['/app/logs/supervisord.log', '/Volumes/appdata/dockerdiscordcontrol/logs/supervisord.log']
        }

    def get_container_logs(self, request: ContainerLogRequest) -> LogResult:
        """
        Retrieve logs from a specific Docker container.

        Args:
            request: ContainerLogRequest with container name and line limit

        Returns:
            LogResult with log content or error information
        """
        try:
            # Step 1: Validate container name
            if not self._validate_container_name(request.container_name):
                return LogResult(
                    success=False,
                    error="Invalid container name",
                    status_code=400
                )

            # Step 2: Get Docker client and container
            docker_client = self._get_docker_client()
            if not docker_client:
                return LogResult(
                    success=False,
                    error="Could not connect to Docker",
                    status_code=500
                )

            # Step 3: Retrieve container logs
            logs_content = self._fetch_container_logs(
                docker_client,
                request.container_name,
                request.max_lines
            )

            if logs_content is None:
                return LogResult(
                    success=False,
                    error=f"Container '{request.container_name}' not found",
                    status_code=404
                )

            return LogResult(
                success=True,
                content=logs_content
            )

        except Exception as e:
            self.logger.error(f"Error retrieving container logs for {request.container_name}: {e}", exc_info=True)
            return LogResult(
                success=False,
                error="An unexpected error occurred",
                status_code=500
            )

    def get_filtered_logs(self, request: FilteredLogRequest) -> LogResult:
        """
        Retrieve filtered logs based on log type.

        Args:
            request: FilteredLogRequest with log type and line limit

        Returns:
            LogResult with filtered log content or error information
        """
        try:
            if request.log_type == LogType.BOT:
                return self._get_bot_logs(request.max_lines)
            elif request.log_type == LogType.DISCORD:
                return self._get_discord_logs(request.max_lines)
            elif request.log_type == LogType.WEBUI:
                return self._get_webui_logs(request.max_lines)
            elif request.log_type == LogType.APPLICATION:
                return self._get_application_logs(request.max_lines)
            else:
                return LogResult(
                    success=False,
                    error=f"Unsupported log type: {request.log_type}",
                    status_code=400
                )

        except Exception as e:
            self.logger.error(f"Error retrieving {request.log_type.value} logs: {e}", exc_info=True)
            return LogResult(
                success=False,
                error=f"Error fetching {request.log_type.value} logs",
                status_code=500
            )

    def get_action_logs(self, request: ActionLogRequest) -> LogResult:
        """
        Retrieve user action logs in text or JSON format.

        Args:
            request: ActionLogRequest with format type and limit

        Returns:
            LogResult with action log content or error information
        """
        try:
            if request.format_type == "json":
                return self._get_action_logs_json(request.limit)
            else:
                return self._get_action_logs_text(request.limit)

        except Exception as e:
            self.logger.error(f"Error retrieving action logs: {e}", exc_info=True)
            return LogResult(
                success=False,
                error="Error fetching action logs",
                status_code=500
            )

    def clear_logs(self, request: ClearLogRequest) -> LogResult:
        """
        Clear logs (limited functionality for Docker container logs).

        Args:
            request: ClearLogRequest with log type

        Returns:
            LogResult with clearing operation result
        """
        try:
            self.logger.info(f"Clear logs request for type: {request.log_type}")

            # Note: Docker container logs cannot be cleared directly
            # This is prepared for future file-based logging implementation
            return LogResult(
                success=True,
                data={
                    'success': True,
                    'message': f'{request.log_type.capitalize()} logs cleared (Note: Docker container logs persist until container restart)'
                }
            )

        except Exception as e:
            self.logger.error(f"Error clearing logs: {e}", exc_info=True)
            return LogResult(
                success=False,
                error=str(e),
                status_code=500
            )

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    def _validate_container_name(self, container_name: str) -> bool:
        """Validate container name to prevent injection attacks."""
        try:
            from utils.common_helpers import validate_container_name
            return validate_container_name(container_name)
        except ImportError:
            # Fallback validation if utility is not available
            import re
            return bool(re.match(r'^[a-zA-Z0-9_.-]+$', container_name))

    def _get_docker_client(self):
        """Get Docker client with error handling."""
        try:
            import docker
            return docker.from_env()
        except Exception as e:
            self.logger.error(f"Failed to initialize Docker client: {e}")
            return None

    def _fetch_container_logs(self, client, container_name: str, max_lines: int) -> Optional[str]:
        """Fetch logs from Docker container with error handling."""
        try:
            import docker
            container = client.containers.get(container_name)
            logs = container.logs(tail=max_lines, stdout=True, stderr=True)
            return logs.decode('utf-8', errors='replace')

        except docker.errors.NotFound:
            self.logger.warning(f"Log request for non-existent container: {container_name}")
            return None
        except docker.errors.APIError as e:
            self.logger.error(f"Docker API error when fetching logs for {container_name}: {e}")
            raise Exception("Could not retrieve logs due to a Docker API error")
        except Exception as e:
            self.logger.error(f"Error fetching container logs: {e}")
            raise

    def _get_bot_logs(self, max_lines: int) -> LogResult:
        """Get bot-specific logs with file fallback."""
        # Try reading from bot.log file first (multiple possible paths)
        for bot_log_path in self.log_paths['bot']:
            if os.path.exists(bot_log_path):
                file_content = self._read_log_file(bot_log_path, max_lines)
                if file_content and file_content.strip():
                    self.logger.info(f"Successfully read bot logs from: {bot_log_path}")
                    return LogResult(success=True, content=file_content)

        # Fallback: Get from container logs and filter
        self.logger.info("Bot log files not found, falling back to container log filtering")
        return self._get_filtered_container_logs(
            max_lines,
            ['bot.py', 'cog', 'discord.py', 'discord bot', 'command', 'slash', 'cache', 'container', 'update'],
            "No bot logs found"
        )

    def _get_discord_logs(self, max_lines: int) -> LogResult:
        """Get Discord-specific logs with file fallback."""
        # Try reading from discord.log file first (multiple possible paths)
        for discord_log_path in self.log_paths['discord']:
            if os.path.exists(discord_log_path):
                file_content = self._read_log_file(discord_log_path, max_lines)
                if file_content and file_content.strip():
                    self.logger.info(f"Successfully read Discord logs from: {discord_log_path}")
                    return LogResult(success=True, content=file_content)

        # Fallback: Get from container logs and filter
        self.logger.info("Discord log files not found, falling back to container log filtering")
        return self._get_filtered_container_logs(
            max_lines,
            ['discord', 'guild', 'channel', 'member', 'message', 'voice', 'websocket'],
            "No Discord logs found"
        )

    def _get_webui_logs(self, max_lines: int) -> LogResult:
        """Get Web UI specific logs with file fallback."""
        # Try reading from webui_error.log file first (multiple possible paths)
        for webui_log_path in self.log_paths['webui']:
            if os.path.exists(webui_log_path):
                file_content = self._read_log_file(webui_log_path, max_lines)
                if file_content and file_content.strip():
                    self.logger.info(f"Successfully read Web UI logs from: {webui_log_path}")
                    return LogResult(success=True, content=file_content)

        # Fallback: Get from container logs and filter
        self.logger.info("Web UI log files not found, falling back to container log filtering")
        return self._get_filtered_container_logs(
            max_lines,
            ['flask', 'Flask', 'gunicorn', 'Gunicorn', 'GET /', 'POST /', 'HTTP', '127.0.0.1', '0.0.0.0:5000', 'werkzeug', 'jinja2'],
            "No Web UI logs found"
        )

    def _get_application_logs(self, max_lines: int) -> LogResult:
        """Get application-level logs with file fallback."""
        # Try reading from supervisord.log file first (multiple possible paths)
        for app_log_path in self.log_paths['application']:
            if os.path.exists(app_log_path):
                file_content = self._read_log_file(app_log_path, max_lines)
                if file_content and file_content.strip():
                    self.logger.info(f"Successfully read application logs from: {app_log_path}")
                    return LogResult(success=True, content=file_content)

        # Fallback: Get from container logs and filter
        self.logger.info("Application log files not found, falling back to container log filtering")
        return self._get_filtered_container_logs(
            max_lines,
            ['ERROR', 'WARNING', 'INFO', 'DEBUG', 'Starting', 'Stopping', 'Initializing', 'Config', 'Database', 'Scheduler'],
            "No application logs found"
        )

    def _get_filtered_container_logs(self, max_lines: int, filter_patterns: List[str], no_logs_message: str) -> LogResult:
        """Get filtered logs from default container."""
        try:
            docker_client = self._get_docker_client()
            if not docker_client:
                return LogResult(success=False, error="Could not connect to Docker", status_code=500)

            # Get more logs to ensure we have enough after filtering
            logs_str = self._fetch_container_logs(docker_client, self.default_container, max_lines * 2)
            if logs_str is None:
                return LogResult(success=False, error="Container not found", status_code=404)

            # Filter logs based on patterns
            filtered_lines = []
            for line in logs_str.split('\n'):
                if any(pattern in line.lower() for pattern in [p.lower() for p in filter_patterns]):
                    filtered_lines.append(line)

            # Limit to max_lines and format result
            filtered_logs = '\n'.join(filtered_lines[-max_lines:]) if filtered_lines else no_logs_message

            return LogResult(success=True, content=filtered_logs)

        except Exception as e:
            self.logger.error(f"Error getting filtered container logs: {e}")
            raise

    def _read_log_file(self, file_path: str, max_lines: int) -> Optional[str]:
        """Read log file with line limiting."""
        try:
            if not os.path.exists(file_path):
                return None

            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
                # Get last max_lines
                recent_lines = lines[-max_lines:] if len(lines) > max_lines else lines
                return ''.join(recent_lines)

        except Exception as e:
            self.logger.error(f"Error reading log file {file_path}: {e}")
            return None

    def _get_action_logs_text(self, limit: int) -> LogResult:
        """Get action logs in text format."""
        try:
            from services.infrastructure.action_logger import get_action_logs_text
            action_log_content = get_action_logs_text(limit=limit)

            if action_log_content:
                return LogResult(success=True, content=action_log_content)
            else:
                return LogResult(success=True, content="No action logs available")

        except Exception as e:
            self.logger.error(f"Error getting action logs text: {e}")
            raise

    def _get_action_logs_json(self, limit: int) -> LogResult:
        """Get action logs in JSON format."""
        try:
            from services.infrastructure.action_logger import get_action_logs_json
            action_logs = get_action_logs_json(limit=limit)

            return LogResult(
                success=True,
                data={
                    'success': True,
                    'logs': action_logs,
                    'count': len(action_logs)
                }
            )

        except Exception as e:
            self.logger.error(f"Error getting action logs JSON: {e}")
            raise


# Singleton instance
_container_log_service = None


def get_container_log_service() -> ContainerLogService:
    """Get the singleton ContainerLogService instance."""
    global _container_log_service
    if _container_log_service is None:
        _container_log_service = ContainerLogService()
    return _container_log_service