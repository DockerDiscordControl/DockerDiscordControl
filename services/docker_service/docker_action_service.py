# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Docker Action Service (SERVICE FIRST)         #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
SERVICE FIRST Docker Action Service for container operations.
Replaces old docker_utils.docker_action with proper Request/Result pattern.
"""

import asyncio
import logging
import time
import docker
from dataclasses import dataclass
from typing import Optional
from utils.logging_utils import get_module_logger

logger = get_module_logger('docker_action_service')


# ============================================================================ #
# SERVICE FIRST REQUEST/RESULT DATACLASSES                                     #
# ============================================================================ #

@dataclass(frozen=True)
class DockerActionRequest:
    """Request for Docker container action."""
    container_name: str
    action: str  # 'start', 'stop', 'restart'
    timeout_seconds: float = 30.0
    validate_name: bool = True  # Security validation


@dataclass(frozen=True)
class DockerActionResult:
    """Result of Docker container action."""
    success: bool
    container_name: str
    action: str

    # Performance metadata
    execution_time_ms: float = 0.0

    # Error information
    error_message: Optional[str] = None
    error_type: Optional[str] = None  # 'not_found', 'invalid_action', 'validation_failed', 'docker_error'


# ============================================================================ #
# DOCKER ACTION SERVICE                                                         #
# ============================================================================ #

class DockerActionService:
    """
    SERVICE FIRST Docker action service for container operations.

    Features:
    - Request/Result dataclass pattern
    - Comprehensive error handling
    - Security validation
    - Performance monitoring
    - Docker client pool integration
    """

    def __init__(self):
        self.logger = logger.getChild(self.__class__.__name__)

        # Valid actions mapping
        self._valid_actions = {
            'start': lambda c: c.start(),
            'stop': lambda c: c.stop(),
            'restart': lambda c: c.restart(),
        }

        self.logger.info("Docker Action Service initialized (SERVICE FIRST)")

    async def execute_docker_action(self, request: DockerActionRequest) -> DockerActionResult:
        """
        Execute Docker container action using SERVICE FIRST pattern.

        Args:
            request: DockerActionRequest with container name and action

        Returns:
            DockerActionResult with execution status and metadata
        """
        start_time = time.time()

        try:
            # Validate action
            if request.action not in self._valid_actions:
                return DockerActionResult(
                    success=False,
                    container_name=request.container_name,
                    action=request.action,
                    error_message=f"Invalid Docker action: {request.action}. Valid actions: {list(self._valid_actions.keys())}",
                    error_type="invalid_action",
                    execution_time_ms=(time.time() - start_time) * 1000
                )

            # Validate container name
            if not request.container_name:
                return DockerActionResult(
                    success=False,
                    container_name=request.container_name,
                    action=request.action,
                    error_message="No container name provided",
                    error_type="validation_failed",
                    execution_time_ms=(time.time() - start_time) * 1000
                )

            # Security validation
            if request.validate_name:
                if not self._validate_container_name(request.container_name):
                    return DockerActionResult(
                        success=False,
                        container_name=request.container_name,
                        action=request.action,
                        error_message=f"Invalid container name format: {request.container_name}",
                        error_type="validation_failed",
                        execution_time_ms=(time.time() - start_time) * 1000
                    )

            # Execute action using Docker client service
            from services.docker_service.docker_client_pool import get_docker_client_async

            async with get_docker_client_async(
                timeout=request.timeout_seconds,
                operation='action',
                container_name=request.container_name
            ) as client:

                # Get container
                try:
                    container = await asyncio.to_thread(client.containers.get, request.container_name)
                except docker.errors.NotFound:
                    return DockerActionResult(
                        success=False,
                        container_name=request.container_name,
                        action=request.action,
                        error_message=f"Container '{request.container_name}' not found",
                        error_type="not_found",
                        execution_time_ms=(time.time() - start_time) * 1000
                    )

                # Execute action
                action_func = self._valid_actions[request.action]
                await asyncio.to_thread(action_func, container)

                execution_time_ms = (time.time() - start_time) * 1000

                self.logger.info(
                    f"Docker action '{request.action}' on container '{request.container_name}' "
                    f"completed successfully in {execution_time_ms:.1f}ms"
                )

                return DockerActionResult(
                    success=True,
                    container_name=request.container_name,
                    action=request.action,
                    execution_time_ms=execution_time_ms
                )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000

            self.logger.error(
                f"Unexpected error during docker action '{request.action}' on '{request.container_name}': {e}",
                exc_info=True
            )

            return DockerActionResult(
                success=False,
                container_name=request.container_name,
                action=request.action,
                error_message=str(e),
                error_type="docker_error",
                execution_time_ms=execution_time_ms
            )

    def _validate_container_name(self, container_name: str) -> bool:
        """Validate container name format for security."""
        try:
            from utils.common_helpers import validate_container_name
            return validate_container_name(container_name)
        except ImportError:
            # Fallback validation if helper not available
            import re
            # Basic validation: alphanumeric, hyphens, underscores
            return bool(re.match(r'^[a-zA-Z0-9_-]+$', container_name))


# ============================================================================ #
# SERVICE INSTANCE                                                              #
# ============================================================================ #

# Global service instance
_docker_action_service: Optional[DockerActionService] = None


def get_docker_action_service() -> DockerActionService:
    """Get the global Docker action service instance."""
    global _docker_action_service
    if _docker_action_service is None:
        _docker_action_service = DockerActionService()
    return _docker_action_service


# ============================================================================ #
# COMPATIBILITY LAYER                                                           #
# ============================================================================ #

async def docker_action_service_first(container_name: str, action: str, timeout: float = 30.0) -> bool:
    """
    SERVICE FIRST replacement for old docker_action function.

    Args:
        container_name: Name of the container
        action: Action to perform ('start', 'stop', 'restart')
        timeout: Timeout in seconds

    Returns:
        bool: True if successful, False otherwise
    """
    service = get_docker_action_service()
    request = DockerActionRequest(
        container_name=container_name,
        action=action,
        timeout_seconds=timeout
    )

    result = await service.execute_docker_action(request)
    return result.success