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

from utils.logging_utils import get_module_logger
import os
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from services.exceptions import ContainerLogError

logger = get_module_logger('container_log_service')


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

        # Log file paths: the Docker path first, then the local checkout. The second entry
        # used to be the maintainer's absolute path, which existed on exactly one machine
        # and was searched on every lookup. It is now derived from this file's location.
        local_logs = Path(__file__).resolve().parents[2] / "logs"
        # ONLY files DDC writes. app/bootstrap/runtime.py creates discord.log
        # (INFO+) and bot_error.log (ERROR+), and setup_logger creates one file
        # per logger name; nothing else is ever written.
        #
        # bot.log, webui_error.log and supervisord.log used to be listed here
        # and are written by nobody. supervisord.log is the reason this matters:
        # DDC has run as ONE process since that era ended - the image has no
        # supervisorctl - but the 3.2 MB file from 2025-11-21 was left behind in
        # the logs directory, so the reader below found it and served it under
        # the Application tab as if it were today's. Full of "WARN exited:
        # discord-bot (exit status 1; not expected)". The other two were
        # harmless only because they happened not to exist; one restored backup
        # and they would have been the same trap.
        #
        # A source with no file falls through to the live container output,
        # which in a one-process DDC IS the application log.
        self.log_paths = {
            'bot': [],
            'discord': ['/app/logs/discord.log', str(local_logs / 'discord.log')],
            'webui': [],
            # bot_error.log is the only log that OUTLIVES a rebuild: every
            # other source here reads `docker logs`, which a rebuild empties -
            # and rebuilding is how DDC is deployed, so the evidence vanishes
            # exactly when somebody looks for it after an upgrade. This file
            # is on the mounted volume, ERROR and above, rotated at 5 MB.
            'application': ['/app/logs/bot_error.log', str(local_logs / 'bot_error.log')]
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

            # Step 2: Get logs synchronously (avoids asyncio/gevent conflicts)
            logs_content = self._get_container_logs_sync(
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

        except ContainerLogError as e:
            # A failure that is NOT "no such container" - it gets its own answer
            # instead of borrowing the 404 (review C18).
            self.logger.error(f"Could not read logs for {request.container_name}: {e}")
            return LogResult(
                success=False,
                error=f"Could not read logs for '{request.container_name}': {e}",
                status_code=500
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

        except (ImportError, OSError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            # A superset of what the two helpers re-raise. They catch
            # (ImportError, AttributeError, OSError, TypeError[, ValueError]),
            # log, and raise on purpose - leaving the answer to this clause. But
            # ImportError and OSError were missing here, so exactly the two
            # failures they were written to hand upwards left the service
            # uncaught instead of becoming the polite 500 below (review C23).
            self.logger.error(f"Service error retrieving action logs: {e}", exc_info=True)
            return LogResult(
                success=False,
                error="Error fetching action logs",
                status_code=500
            )

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    def _get_container_logs_sync(self, container_name: str, max_lines: int) -> Optional[str]:
        """Get container logs using synchronous Docker SDK (avoids asyncio/gevent conflicts)."""
        try:
            import docker as _docker
            # Through the one client factory, so the log viewer follows
            # DOCKER_HOST (the v3.0 proxy). It used to hard-code
            # unix:///var/run/docker.sock and would have walked past the proxy.
            from services.docker_service.client_factory import build_docker_client
            client = build_docker_client(timeout=30)
            try:
                container = client.containers.get(container_name)
                logs = container.logs(tail=max_lines, stdout=True, stderr=True)
                return logs.decode('utf-8', errors='replace')
            except _docker.errors.NotFound:
                self.logger.warning(f"Log request for non-existent container: {container_name}")
                return None
            except _docker.errors.APIError as e:
                self.logger.error(f"Docker API error when fetching logs for {container_name}: {e}")
                raise ContainerLogError(f"Docker API error: {e}") from e
            finally:
                client.close()
        except ContainerLogError:
            raise
        except Exception as e:
            # None means ONE thing: the container is genuinely not there. It used
            # to mean everything - an unreachable socket, a permission denied, a
            # timeout - and the caller turned all of it into
            # "Container '<name>' not found", 404. The person troubleshooting the
            # log viewer was told the opposite of what had happened (review C18).
            self.logger.error(f"Failed to get Docker logs synchronously: {e}", exc_info=True)
            raise ContainerLogError(f"Could not read logs: {e}") from e

    def _validate_container_name(self, container_name: str) -> bool:
        """Validate container name to prevent injection attacks."""
        try:
            from utils.common_helpers import validate_container_name
            return validate_container_name(container_name)
        except ImportError:
            # Fallback validation if utility is not available
            import re
            return bool(re.match(r'^[a-zA-Z0-9_.-]+$', container_name))

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
        # The error log first; the container log only if it is not there.
        for app_log_path in self.log_paths['application']:
            if os.path.exists(app_log_path):
                file_content = self._read_log_file(app_log_path, max_lines)
                if file_content and file_content.strip():
                    self.logger.info(f"Successfully read application logs from: {app_log_path}")
                    return LogResult(success=True, content=file_content)

        # Fallback for a fresh install or a cleared volume. Narrowed to things
        # that went wrong: the old list held INFO and DEBUG, so it matched every
        # line DDC has ever written and the tab showed the whole log. Traceback,
        # Exception and CRITICAL are here because the real incidents in a DDC
        # error log are crashes, which never carry the word ERROR on their
        # continuation lines.
        self.logger.debug("No error log file found, falling back to container log filtering")
        return self._get_filtered_container_logs(
            max_lines,
            ['ERROR', 'CRITICAL', 'FATAL', 'Traceback', 'Exception'],
            "No errors recorded"
        )

    def _get_filtered_container_logs(self, max_lines: int, filter_patterns: List[str], no_logs_message: str) -> LogResult:
        """Get filtered logs from default container."""
        try:
            # Get more logs to ensure we have enough after filtering
            logs_str = self._get_container_logs_sync(self.default_container, max_lines * 2)
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

        except ContainerLogError as e:
            # The logs could not be read, and that is NOT "no such container" -
            # it gets its own answer next to the 404 above, the same way
            # get_container_logs answers it (review C18, E46). Without this the
            # exception walks out of the service and out of the route, and the
            # log tab fills with Flask's HTML error page at the exact moment the
            # operator opened it to find out what was wrong.
            self.logger.error(f"Could not read logs for the filtered view: {e}")
            return LogResult(
                success=False,
                error=f"Could not read container logs: {e}",
                status_code=500
            )
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
            from services.infrastructure.action_logger import (
                ActionLogUnreadable, get_action_logs_json)
            try:
                action_logs = get_action_logs_json(limit=limit)
            except ActionLogUnreadable as e:
                # A log that could not be read is a failed request, not an empty
                # history. Without this the empty list came back wrapped in
                # success=True and the route never saw a failure (review D5).
                self.logger.error(f"Action logs could not be read: {e}")
                return LogResult(success=False, error=str(e), status_code=500)

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
