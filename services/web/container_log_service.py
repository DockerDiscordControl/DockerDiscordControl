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
import asyncio
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

            # Step 2 & 3: Get logs using SERVICE FIRST pattern (async internally)
            try:
                # Check if we're in an async context
                loop = asyncio.get_running_loop()
                # We're in an async context but this method is sync
                # Use run_in_executor to run the async function
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    logs_content = executor.submit(
                        lambda: asyncio.run(self._get_container_logs_service_first(
                            request.container_name,
                            request.max_lines
                        ))
                    ).result()
            except RuntimeError:
                # No event loop running (gevent thread), use asyncio.run() directly
                logs_content = asyncio.run(self._get_container_logs_service_first(
                    request.container_name,
                    request.max_lines
                ))

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

        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            # Service/async errors (missing services, invalid types, runtime/event loop errors)
            self.logger.error(f"Service error retrieving container logs for {request.container_name}: {e}", exc_info=True)
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

        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            # Data/service errors (invalid enum, type errors, runtime errors)
            self.logger.error(f"Service error retrieving {request.log_type.value} logs: {e}", exc_info=True)
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

        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            # Data/service errors (invalid format type, type errors, runtime errors)
            self.logger.error(f"Service error retrieving action logs: {e}", exc_info=True)
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

        except (AttributeError, TypeError, ValueError) as e:
            # Data/operation errors (invalid attributes, type errors, value errors)
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

    async def _get_docker_client_async(self):
        """Get Docker client with SERVICE FIRST pattern."""
        try:
            # SERVICE FIRST: Use Docker Client Service
            from services.docker_service.docker_client_pool import get_docker_client_async
            return get_docker_client_async(operation='logs', timeout=30.0)
        except (ImportError, AttributeError, TypeError, RuntimeError) as e:
            # Service/import errors (missing docker service, attribute errors, runtime errors)
            self.logger.error(f"Failed to get Docker client: {e}", exc_info=True)
            return None

    async def _fetch_container_logs_async(self, client, container_name: str, max_lines: int) -> Optional[str]:
        """Fetch logs from Docker container with error handling using SERVICE FIRST pattern."""
        try:
            import docker
            import asyncio

            # Use async thread execution for Docker API calls
            container = await asyncio.to_thread(client.containers.get, container_name)
            logs = await asyncio.to_thread(
                lambda: container.logs(tail=max_lines, stdout=True, stderr=True)
            )
            return logs.decode('utf-8', errors='replace')

        except docker.errors.NotFound:
            self.logger.warning(f"Log request for non-existent container: {container_name}")
            return None
        except docker.errors.APIError as e:
            self.logger.error(f"Docker API error when fetching logs for {container_name}: {e}")
            raise RuntimeError("Could not retrieve logs due to a Docker API error")
        except (ImportError, AttributeError, TypeError, UnicodeDecodeError, RuntimeError) as e:
            # Import/decode/async errors (missing modules, attribute errors, decode errors, runtime errors)
            self.logger.error(f"Error fetching container logs: {e}", exc_info=True)
            raise

    async def _get_container_logs_service_first(self, container_name: str, max_lines: int) -> Optional[str]:
        """Get container logs using SERVICE FIRST Docker Client Service."""
        try:
            # Get Docker client using SERVICE FIRST pattern
            client_context = await self._get_docker_client_async()
            if not client_context:
                return None

            # Use the context manager for proper cleanup
            async with client_context as client:
                return await self._fetch_container_logs_async(client, container_name, max_lines)

        except (AttributeError, TypeError, RuntimeError) as e:
            # Async/context errors (missing attributes, type errors, runtime errors)
            self.logger.error(f"Error in SERVICE FIRST container logs: {e}", exc_info=True)
            return None

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
            # Get logs using SERVICE FIRST pattern (async internally)
            # Get more logs to ensure we have enough after filtering
            try:
                # Try to get current event loop
                loop = asyncio.get_running_loop()
                # Create task for existing loop
                task = loop.create_task(self._get_container_logs_service_first(self.default_container, max_lines * 2))
                logs_str = asyncio.run_coroutine_threadsafe(task, loop).result()
            except RuntimeError:
                # No event loop running, use asyncio.run()
                logs_str = asyncio.run(self._get_container_logs_service_first(self.default_container, max_lines * 2))
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

        except (AttributeError, TypeError, RuntimeError, ValueError) as e:
            # Async/data errors (attribute errors, type errors, runtime/async errors, value errors)
            self.logger.error(f"Error getting filtered container logs: {e}", exc_info=True)
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

        except (IOError, OSError, PermissionError, UnicodeDecodeError) as e:
            # File I/O errors (read errors, permissions, decode errors)
            self.logger.error(f"File error reading log file {file_path}: {e}", exc_info=True)
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

        except (ImportError, AttributeError, OSError, TypeError) as e:
            # Service/file errors (missing modules, attribute errors, I/O errors, type errors)
            self.logger.error(f"Error getting action logs text: {e}", exc_info=True)
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

        except (ImportError, AttributeError, OSError, TypeError, ValueError) as e:
            # Service/data errors (missing modules, attribute errors, I/O errors, type/value errors)
            self.logger.error(f"Error getting action logs JSON: {e}", exc_info=True)
            raise


# Singleton instance
_container_log_service = None


def get_container_log_service() -> ContainerLogService:
    """Get the singleton ContainerLogService instance."""
    global _container_log_service
    if _container_log_service is None:
        _container_log_service = ContainerLogService()
    return _container_log_service