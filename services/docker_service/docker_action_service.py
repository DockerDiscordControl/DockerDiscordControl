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

from services.exceptions import DockerServiceError
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


def get_stop_timeout_kwargs(container) -> dict:
    """
    Timeout kwargs for container.stop()/restart() that honour the container's own StopTimeout.

    docker-py's restart() defaults to timeout=10, which overrides a configured StopTimeout
    (e.g. game servers that need longer to save). stop() lets the daemon use StopTimeout,
    but docker-py then only extends its HTTP read timeout by 10s - passing the value
    explicitly keeps both in sync. Returns {} when no StopTimeout is set (docker-py defaults).
    """
    try:
        stop_timeout = (container.attrs.get('Config') or {}).get('StopTimeout')
    except (AttributeError, TypeError) as e:
        # `{}` here means something completely different from the `{}` below,
        # and the caller cannot tell them apart: down there no StopTimeout is
        # configured, up here the container could not be read at all. Both make
        # restart() fall back to docker-py's timeout=10, which is what a game
        # server that writes its world on shutdown does not survive - and this
        # function is on every stop and restart there is. It has to say so
        # (review E50).
        logger.warning(
            "Could not read the stop timeout of '%s' (%s) - falling back to "
            "docker-py's ten-second default. A container that needs longer to "
            "save may be killed mid-write.",
            getattr(container, 'name', '<unknown container>'), e)
        return {}
    if isinstance(stop_timeout, int) and not isinstance(stop_timeout, bool) and stop_timeout >= 0:
        return {'timeout': stop_timeout}
    return {}


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
            'stop': lambda c: c.stop(**get_stop_timeout_kwargs(c)),
            'restart': lambda c: c.restart(**get_stop_timeout_kwargs(c)),
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

                # So the watchdog does not report DDC's own stop as an alarm -
                # noted BEFORE the call. A stop that outlasts the client's read
                # timeout raises here while Docker carries it out; noted only
                # after success (until 2026-09-26), it was reported as an alarm
                # and a restart rule could undo it. Taken back only when Docker
                # itself refused, because then nothing happened.
                from services.automation.own_actions import forget, note_own_action
                note_own_action(request.container_name, request.action)

                # Execute action
                action_func = self._valid_actions[request.action]
                try:
                    await asyncio.to_thread(action_func, container)
                except docker.errors.APIError:
                    forget(request.container_name)
                    raise

                execution_time_ms = (time.time() - start_time) * 1000

                self.logger.info(
                    f"Docker action '{request.action}' on container '{request.container_name}' "
                    f"completed successfully in {execution_time_ms:.1f}ms"
                )

                # Invalidate BOTH caches after successful Docker action
                # This ensures immediate status updates for all Docker operations
                try:
                    # 1. StatusCacheService (used for periodic updates)
                    from services.status.status_cache_service import get_status_cache_service
                    status_cache_service = get_status_cache_service()
                    if status_cache_service.get(request.container_name):
                        status_cache_service.remove(request.container_name)
                        self.logger.debug(f"Invalidated StatusCacheService cache for {request.container_name}")

                    # 2. ContainerStatusService (has its own 30s cache!)
                    from services.infrastructure.container_status_service import get_container_status_service
                    container_status_service = get_container_status_service()
                    container_status_service.invalidate_container(request.container_name)
                    self.logger.debug(f"Invalidated ContainerStatusService cache for {request.container_name}")

                except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException) as e:
                    # Don't fail the action if cache invalidation fails
                    self.logger.warning(f"Failed to invalidate cache for {request.container_name}: {e}")

                return DockerActionResult(
                    success=True,
                    container_name=request.container_name,
                    action=request.action,
                    execution_time_ms=execution_time_ms
                )

        # OSError covers requests' ReadTimeout/ConnectionError (e.g. a stop() that outlasts
        # the HTTP read timeout) so the caller gets a clean failure instead of an exception
        # DockerServiceError first, because it is the one the comment above was
        # already promising to turn into a clean failure and did not: the
        # `async with get_docker_client_async(...)` above raises
        # DockerConnectionError when the daemon cannot be reached at all
        # (review E45).
        except (DockerServiceError, RuntimeError, OSError, docker.errors.APIError, docker.errors.DockerException) as e:
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
    # A GROUP is a name like any other (operator, 2026-09-24): everything that
    # acts on a container comes through here, so this is where "group:Gameserver"
    # becomes its members. The walk itself lives in one place, shared with the
    # scheduled tasks - see services/docker_service/group_actions.py.
    from services.docker_service.group_actions import act_on_group, group_name_of, is_group_target

    if is_group_target(container_name):
        outcome = await act_on_group(group_name_of(container_name), action, timeout)
        return outcome.success

    service = get_docker_action_service()
    request = DockerActionRequest(
        container_name=container_name,
        action=action,
        timeout_seconds=timeout
    )

    result = await service.execute_docker_action(request)
    return result.success
