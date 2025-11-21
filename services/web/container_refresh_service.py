#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Container Refresh Service                      #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Container Refresh Service - Handles Docker container refresh operations with timestamp formatting
"""

import logging
import time
import pytz
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
import docker

logger = logging.getLogger(__name__)


@dataclass
class ContainerRefreshRequest:
    """Represents a container refresh request."""
    pass


@dataclass
class ContainerRefreshResult:
    """Represents the result of container refresh operation."""
    success: bool
    message: str
    container_count: Optional[int] = None
    timestamp: Optional[float] = None
    formatted_time: Optional[str] = None
    error: Optional[str] = None


class ContainerRefreshService:
    """Service for handling Docker container refresh operations."""

    def __init__(self):
        self.logger = logger

    def refresh_containers(self, request: ContainerRefreshRequest) -> ContainerRefreshResult:
        """
        Force refresh of Docker container list with comprehensive business logic.

        Args:
            request: ContainerRefreshRequest (currently no specific data needed)

        Returns:
            ContainerRefreshResult with refresh status and details
        """
        try:
            # Step 1: Initialize dependencies
            dependencies = self._initialize_dependencies()
            if not dependencies['success']:
                return ContainerRefreshResult(
                    success=False,
                    message="Failed to initialize dependencies",
                    error=dependencies['error']
                )

            # Step 2: Perform Docker container refresh
            refresh_result = self._perform_docker_refresh(dependencies)
            if not refresh_result['success']:
                return ContainerRefreshResult(
                    success=False,
                    message="Container refresh failed",
                    error=refresh_result['error']
                )

            # Step 3: Log the action
            self._log_refresh_action()

            # Step 4: Get and format timestamp
            timestamp_info = self._get_formatted_timestamp(dependencies)

            # Step 5: Build successful response
            return ContainerRefreshResult(
                success=True,
                message="Container list refreshed successfully",
                container_count=refresh_result['container_count'],
                timestamp=timestamp_info['timestamp'],
                formatted_time=timestamp_info['formatted_time']
            )

        except (AttributeError, KeyError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException) as e:
            self.logger.error(f"Error refreshing containers: {e}", exc_info=True)
            return ContainerRefreshResult(
                success=False,
                error=f"Unexpected error refreshing containers: {str(e)}"
            )

    def _initialize_dependencies(self) -> dict:
        """Initialize and validate required dependencies."""
        try:
            from app.utils.web_helpers import get_docker_containers_live, docker_cache
            from services.config.config_service import load_config
            from services.infrastructure.action_logger import log_user_action

            return {
                'success': True,
                'get_docker_containers_live': get_docker_containers_live,
                'docker_cache': docker_cache,
                'load_config': load_config,
                'log_user_action': log_user_action
            }

        except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            return {
                'success': False,
                'error': f"Failed to initialize dependencies: {str(e)}"
            }

    def _perform_docker_refresh(self, dependencies: dict) -> dict:
        """Perform the actual Docker container refresh."""
        try:
            self.logger.info("Manual refresh of Docker container list requested")

            # Get Docker containers with force_refresh=True
            containers, error = dependencies['get_docker_containers_live'](
                self.logger,
                force_refresh=True
            )

            if error:
                self.logger.warning(f"Error during manual container refresh: {error}")
                return {
                    'success': False,
                    'error': "Error refreshing containers. Please check the logs for details."
                }

            return {
                'success': True,
                'container_count': len(containers)
            }

        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            self.logger.error(f"Error performing Docker refresh: {e}", exc_info=True)
            return {
                'success': False,
                'error': f"Error performing Docker refresh: {str(e)}"
            }

    def _log_refresh_action(self) -> None:
        """Log the container refresh action."""
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action("REFRESH", "Docker Container List", source="Web UI ContainerRefreshService")
        except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException) as e:
            self.logger.warning(f"Failed to log refresh action: {e}")

    def _get_formatted_timestamp(self, dependencies: dict) -> dict:
        """Get and format the refresh timestamp with timezone support."""
        try:
            # Get the timestamp from Docker cache
            timestamp = dependencies['docker_cache'].get('global_timestamp', time.time())

            # Load configuration for timezone
            config = dependencies['load_config']()
            timezone_str = config.get('timezone', 'Europe/Berlin')

            # Format timestamp with configured timezone
            try:
                tz = pytz.timezone(timezone_str)
                dt = datetime.fromtimestamp(timestamp, tz=tz)
                formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
            except (RuntimeError) as e:
                self.logger.error(f"Error formatting timestamp with timezone: {e}", exc_info=True)
                # Fallback to system timezone
                formatted_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

            return {
                'timestamp': timestamp,
                'formatted_time': formatted_time
            }

        except (RuntimeError) as e:
            self.logger.error(f"Error getting formatted timestamp: {e}", exc_info=True)
            # Return basic timestamp as fallback
            return {
                'timestamp': time.time(),
                'formatted_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }


# Singleton instance
_container_refresh_service = None


def get_container_refresh_service() -> ContainerRefreshService:
    """Get the singleton ContainerRefreshService instance."""
    global _container_refresh_service
    if _container_refresh_service is None:
        _container_refresh_service = ContainerRefreshService()
    return _container_refresh_service
