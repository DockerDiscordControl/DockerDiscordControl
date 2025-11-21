# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Docker Client Service (SERVICE FIRST)         #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
SERVICE FIRST Docker client connection service with intelligent pooling.
Provides Docker client access with proper performance monitoring and caching.
"""

import docker
import threading
import time
import logging
import asyncio
from typing import Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace

# Import custom exceptions
from services.exceptions import (
    DockerServiceError, DockerConnectionError, DockerCommandTimeoutError,
    DockerClientPoolExhausted
)

logger = logging.getLogger('ddc.docker_client_service')


# ============================================================================ #
# SERVICE FIRST REQUEST/RESULT DATACLASSES                                     #
# ============================================================================ #

@dataclass(frozen=True)
class DockerClientRequest:
    """Request for Docker client access."""
    operation: str = 'default'  # 'stats', 'info', 'action', 'list', etc.
    container_name: Optional[str] = None
    timeout_seconds: float = 30.0
    priority: str = 'normal'  # 'low', 'normal', 'high'

@dataclass(frozen=True)
class DockerClientResult:
    """Result of Docker client request."""
    success: bool
    client: Optional[docker.DockerClient] = None
    error_message: Optional[str] = None
    error_type: Optional[str] = None  # 'timeout', 'connection_failed', 'config_error'

    # Performance metadata
    queue_wait_time_ms: float = 0.0
    connection_time_ms: float = 0.0
    total_time_ms: float = 0.0

    # Pool statistics
    pool_size: int = 0
    active_connections: int = 0
    queue_depth: int = 0

@dataclass(frozen=True)
class DockerPoolStatsRequest:
    """Request for Docker pool statistics."""
    include_performance_history: bool = False

@dataclass(frozen=True)
class DockerPoolStatsResult:
    """Result containing Docker pool statistics."""
    success: bool

    # Current pool state
    total_connections: int = 0
    active_connections: int = 0
    available_connections: int = 0
    queue_size: int = 0
    max_connections: int = 0

    # Performance statistics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_requests: int = 0
    average_wait_time_ms: float = 0.0
    max_queue_size_reached: int = 0

    # Optional performance history
    performance_history: Optional[dict] = None
    error_message: Optional[str] = None


# ============================================================================ #
# INTERNAL QUEUE MANAGEMENT                                                     #
# ============================================================================ #

@dataclass
class QueueRequest:
    """Represents a queued client request."""
    request_id: str
    timestamp: float
    timeout: float
    future: asyncio.Future


class DockerClientService:
    """
    SERVICE FIRST Docker client service with intelligent connection pooling.

    Features:
    - Request/Result pattern for consistent API
    - Intelligent connection pooling with queue management
    - Performance monitoring and statistics
    - Automatic connection health checking
    - Smart timeout configuration from docker_config.json
    """

    def __init__(self, max_connections: int = 3, timeout: int = 300):
        self._pool = []
        self._in_use = []
        self._max_connections = max_connections
        self._timeout = timeout
        self._async_lock = asyncio.Lock()
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # Cleanup every 60 seconds

        # Queue system
        self._queue = asyncio.Queue()
        self._queue_processor_task = None
        self._queue_stats = {
            'total_requests': 0,
            'queued_requests': 0,
            'max_queue_size': 0,
            'average_wait_time': 0.0,
            'timeouts': 0
        }

        # Event to signal when clients become available (to avoid busy waiting)
        self._client_available_event = None

        # Start queue processor
        self._start_queue_processor()

    # ========================================================================= #
    # SERVICE FIRST API METHODS                                                #
    # ========================================================================= #

    async def get_docker_client_service(self, request: DockerClientRequest) -> DockerClientResult:
        """
        SERVICE FIRST method to get Docker client access.

        Args:
            request: DockerClientRequest with operation details

        Returns:
            DockerClientResult with client or error information
        """
        start_time = time.time()
        request_id = f"{id(self)}_{time.time()}"

        try:
            logger.debug(f"[SERVICE] Request {request_id}: Getting Docker client for {request.operation} operation")

            # Update pool statistics
            queue_size = self._queue.qsize()
            self._queue_stats['total_requests'] += 1

            # Try immediate acquisition first (fast path)
            try:
                client = await self._try_immediate_acquire()
                if client:
                    connection_time = (time.time() - start_time) * 1000
                    logger.debug(f"[SERVICE] Request {request_id}: Fast path success in {connection_time:.1f}ms")

                    return DockerClientResult(
                        success=True,
                        client=client,
                        queue_wait_time_ms=0.0,
                        connection_time_ms=connection_time,
                        total_time_ms=connection_time,
                        pool_size=len(self._pool),
                        active_connections=len(self._in_use),
                        queue_depth=queue_size
                    )
            except (RuntimeError, ValueError, AttributeError) as e:
                # Fast path failed (pool empty, lock issues, etc.) - fall back to queue
                logger.debug(f"[SERVICE] Request {request_id}: Fast path failed: {e}. Using queue.")

            # Queue the request (slow path)
            future = asyncio.Future()
            queue_request = QueueRequest(
                request_id=request_id,
                timestamp=time.time(),
                timeout=request.timeout_seconds,
                future=future
            )

            logger.debug(f"[SERVICE] Request {request_id}: Queued at position {queue_size + 1}")
            await self._queue.put(queue_request)

            try:
                # Wait for the client with generous queue timeout
                queue_timeout = max(90.0, request.timeout_seconds * 3)
                client = await asyncio.wait_for(future, timeout=queue_timeout)

                total_time = (time.time() - start_time) * 1000
                queue_wait_time = total_time  # Since this was queued, most time was waiting

                return DockerClientResult(
                    success=True,
                    client=client,
                    queue_wait_time_ms=queue_wait_time,
                    connection_time_ms=0.0,  # Already connected when returned from queue
                    total_time_ms=total_time,
                    pool_size=len(self._pool),
                    active_connections=len(self._in_use),
                    queue_depth=self._queue.qsize()
                )

            except asyncio.TimeoutError:
                total_wait = time.time() - start_time
                error_msg = f"Request timed out after {total_wait:.1f}s total wait (queue_timeout was {queue_timeout}s)"
                logger.warning(f"[SERVICE] Request {request_id}: TIMEOUT - {error_msg}")

                self._queue_stats['timeouts'] += 1
                return DockerClientResult(
                    success=False,
                    error_message=error_msg,
                    error_type="timeout",
                    total_time_ms=(time.time() - start_time) * 1000,
                    pool_size=len(self._pool),
                    active_connections=len(self._in_use),
                    queue_depth=self._queue.qsize()
                )

        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            # Queue/async operation errors, pool state errors
            total_time = (time.time() - start_time) * 1000
            error_msg = f"Docker client service error: {e}"
            logger.error(f"[SERVICE] Request {request_id}: ERROR - {error_msg}", exc_info=True)

            return DockerClientResult(
                success=False,
                error_message=error_msg,
                error_type="service_error",
                total_time_ms=total_time,
                pool_size=len(self._pool),
                active_connections=len(self._in_use),
                queue_depth=self._queue.qsize()
            )

    async def release_docker_client_service(self, client: docker.DockerClient) -> bool:
        """
        SERVICE FIRST method to release Docker client back to pool.

        Args:
            client: Docker client to release

        Returns:
            True if successfully released, False otherwise
        """
        try:
            await self._release_client_async(client)
            return True
        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            logger.error(f"Error releasing Docker client: {e}", exc_info=True)
            return False

    async def get_pool_stats_service(self, request: DockerPoolStatsRequest) -> DockerPoolStatsResult:
        """
        SERVICE FIRST method to get Docker pool statistics.

        Args:
            request: DockerPoolStatsRequest

        Returns:
            DockerPoolStatsResult with pool statistics
        """
        try:
            stats = self.get_queue_stats()

            result = DockerPoolStatsResult(
                success=True,
                total_connections=stats['available_clients'] + stats['clients_in_use'],
                active_connections=stats['clients_in_use'],
                available_connections=stats['available_clients'],
                queue_size=stats['current_queue_size'],
                max_connections=stats['max_connections'],
                total_requests=stats['total_requests'],
                successful_requests=stats['total_requests'] - stats['timeouts'],
                failed_requests=stats['timeouts'],
                timeout_requests=stats['timeouts'],
                average_wait_time_ms=stats['average_wait_time'] * 1000,  # Convert to ms
                max_queue_size_reached=stats['max_queue_size']
            )

            if request.include_performance_history:
                # Use dataclasses.replace() for frozen dataclass
                result = replace(result, performance_history=stats)

            return result

        except (KeyError, ValueError, AttributeError, TypeError) as e:
            logger.error(f"Error getting pool stats: {e}", exc_info=True)
            return DockerPoolStatsResult(
                success=False,
                error_message=str(e)
            )

    def _start_queue_processor(self):
        """Start the background queue processor."""
        if self._queue_processor_task is None:
            try:
                loop = asyncio.get_running_loop()
                self._client_available_event = asyncio.Event()
                self._queue_processor_task = loop.create_task(self._process_queue())
                logger.debug("Queue processor started")
            except RuntimeError:
                # No running loop, processor will be started when first async call is made
                logger.debug("No running loop found, queue processor will start on first async call")

    async def _process_queue(self):
        """Process queued requests in background."""
        while True:
            try:
                # Wait for a queued request
                request = await self._queue.get()

                # Check if request has timed out (very generous timeout for queue)
                queue_timeout = max(90.0, request.timeout * 3)  # At least 90s or 3x operation timeout
                if time.time() - request.timestamp > queue_timeout:
                    self._queue_stats['timeouts'] += 1
                    request.future.set_exception(asyncio.TimeoutError(f"Request timed out in queue after {queue_timeout}s"))
                    self._queue.task_done()
                    continue

                # Wait for a client to become available (event-driven, no busy waiting!)
                client = None
                while client is None:
                    try:
                        client = await self._try_acquire_client_for_queue()
                        if client is None:
                            # Pool is full, wait for a client to be released
                            remaining_time = queue_timeout - (time.time() - request.timestamp)
                            if remaining_time <= 0:
                                self._queue_stats['timeouts'] += 1
                                request.future.set_exception(asyncio.TimeoutError(f"Request timed out in queue after {queue_timeout}s"))
                                self._queue.task_done()
                                break

                            # Wait for client to become available or timeout
                            try:
                                await asyncio.wait_for(self._client_available_event.wait(), timeout=remaining_time)
                                self._client_available_event.clear()  # Reset event for next waiter
                            except asyncio.TimeoutError:
                                self._queue_stats['timeouts'] += 1
                                request.future.set_exception(asyncio.TimeoutError(f"Request timed out in queue after {queue_timeout}s"))
                                self._queue.task_done()
                                break
                    except (RuntimeError, ValueError, AttributeError) as e:
                        # Queue state errors, event errors
                        request.future.set_exception(e)
                        self._queue.task_done()
                        break

                # If we got a client, complete the request
                if client is not None:
                    wait_time = time.time() - request.timestamp

                    # Update statistics
                    self._update_queue_stats(wait_time)

                    # Complete the request
                    request.future.set_result(client)
                    logger.debug(f"Request {request.request_id} served after {wait_time:.3f}s wait")
                    self._queue.task_done()

            except asyncio.CancelledError:
                logger.debug("Queue processor cancelled")
                break
            except (RuntimeError, ValueError, AttributeError, OSError) as e:
                logger.error(f"Error in queue processor: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause before retrying

    @asynccontextmanager
    async def get_client_async(self, timeout: float = 10.0):
        """Async context manager for getting Docker client with queue support."""
        request_id = f"{id(self)}_{time.time()}"
        logger.debug(f"[POOL] Request {request_id}: Requesting client with timeout={timeout}s")

        # Update queue stats
        queue_size = self._queue.qsize()
        self._queue_stats['total_requests'] += 1
        self._queue_stats['queued_requests'] = queue_size + 1
        self._queue_stats['max_queue_size'] = max(
            self._queue_stats['max_queue_size'],
            queue_size + 1
        )

        # Ensure queue processor is running (late initialization if needed)
        if self._queue_processor_task is None:
            try:
                loop = asyncio.get_running_loop()
                if self._client_available_event is None:
                    self._client_available_event = asyncio.Event()
                self._queue_processor_task = loop.create_task(self._process_queue())
                logger.debug("Queue processor started (late initialization)")
            except RuntimeError:
                logger.error("Failed to start queue processor - no running event loop")

        # Try immediate acquisition first (fast path)
        fast_path_start = time.time()
        try:
            client = await self._try_immediate_acquire()
            if client:
                fast_path_time = (time.time() - fast_path_start) * 1000
                logger.debug(f"[POOL] Request {request_id}: Fast path success in {fast_path_time:.1f}ms")
                try:
                    yield client
                finally:
                    await self._release_client_async(client)
                return
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.debug(f"[POOL] Request {request_id}: Fast path failed: {e}. Using queue.")
            pass  # Fall back to queue

        # Queue the request (slow path)
        future = asyncio.Future()
        request = QueueRequest(
            request_id=request_id,
            timestamp=time.time(),
            timeout=timeout,
            future=future
        )

        logger.debug(f"[POOL] Request {request_id}: Queued at position {queue_size + 1}")
        await self._queue.put(request)

        try:
            # Wait for the client with very generous queue timeout (90s for queue + operation)
            # The actual Docker operation timeout is handled separately by the caller
            queue_timeout = max(90.0, timeout * 3)  # At least 90s or 3x operation timeout
            client = await asyncio.wait_for(future, timeout=queue_timeout)
            try:
                yield client
            finally:
                await self._release_client_async(client)
        except asyncio.TimeoutError:
            total_wait = time.time() - request.timestamp
            logger.warning(f"[POOL] Request {request_id}: TIMEOUT after {total_wait:.1f}s total wait (queue_timeout was {queue_timeout}s)")
            raise

    async def _try_immediate_acquire(self) -> Optional[docker.DockerClient]:
        """Try to acquire a client immediately without queueing."""
        async with self._async_lock:
            # Cleanup old connections periodically
            if time.time() - self._last_cleanup > self._cleanup_interval:
                await self._cleanup_stale_connections()

            # Try to reuse existing client
            if self._pool:
                client = self._pool.pop()
                self._in_use.append(client)
                try:
                    # Quick ping to verify connection is alive
                    await asyncio.to_thread(client.ping)
                    return client
                except (docker.errors.DockerException, OSError, RuntimeError) as e:
                    # Connection is dead, remove and try creating new one
                    logger.debug(f"Dead connection detected: {e}")
                    self._in_use.remove(client)
                    if len(self._in_use) < self._max_connections:
                        return await self._create_new_client_async()

            # Create new client if under limit
            if len(self._in_use) < self._max_connections:
                return await self._create_new_client_async()

            # Pool is full, need to queue
            return None

    async def _try_acquire_client_for_queue(self) -> Optional[docker.DockerClient]:
        """Try to acquire client for queue processing. Returns None if pool is full."""
        async with self._async_lock:
            # Check if we can reuse existing client first
            if self._pool:
                client = self._pool.pop()
                self._in_use.append(client)
                try:
                    await asyncio.to_thread(client.ping)
                    return client
                except (docker.errors.DockerException, OSError, RuntimeError) as e:
                    logger.debug(f"Dead connection in queue acquisition: {e}")
                    self._in_use.remove(client)
                    # Continue to try creating a new client

            # Check if we can create new client
            if len(self._in_use) < self._max_connections:
                return await self._create_new_client_async()

            # Pool is full, return None to signal queue processor to wait
            return None

    async def _create_new_client_async(self) -> docker.DockerClient:
        """Create a new Docker client async with proper Docker configuration."""
        try:
            # Load Docker configuration from config files (like the old working version)
            from services.config.config_service import load_config
            config = load_config()
            docker_config = config.get('docker_config', {})
            socket_path = docker_config.get('docker_socket_path', '/var/run/docker.sock')

            # Create client with configured socket path (like old working implementation)
            client = await asyncio.to_thread(
                docker.DockerClient,
                base_url=f'unix://{socket_path}',
                timeout=30
            )

            # Test the connection immediately
            await asyncio.to_thread(client.ping)

            self._in_use.append(client)
            logger.debug(f"Created Docker client with socket: {socket_path}")
            return client

        except (docker.errors.DockerException, OSError, RuntimeError) as e:
            logger.warning(f"Failed to create Docker client with config socket: {e}")
            # Fallback to docker.from_env (original behavior)
            try:
                client = await asyncio.to_thread(docker.from_env)
                await asyncio.to_thread(client.ping)  # Test connection
                self._in_use.append(client)
                logger.debug("Created Docker client with docker.from_env fallback")
                return client
            except (docker.errors.DockerException, OSError, RuntimeError) as e2:
                logger.error(f"All Docker client creation methods failed: config={e}, from_env={e2}")
                raise DockerConnectionError(
                    "Failed to create Docker client",
                    error_code="DOCKER_CLIENT_CREATION_FAILED",
                    details={'config_error': str(e), 'from_env_error': str(e2)}
                )

    async def _release_client_async(self, client: docker.DockerClient):
        """Release a client back to the pool async."""
        async with self._async_lock:
            if client in self._in_use:
                self._in_use.remove(client)
                self._pool.append(client)
                logger.debug(f"Client released back to pool (available: {len(self._pool)})")

                # Signal queue processor that a client is now available
                if self._client_available_event:
                    self._client_available_event.set()

    def _update_queue_stats(self, wait_time: float):
        """Update queue statistics."""
        # Simple moving average for wait time
        current_avg = self._queue_stats['average_wait_time']
        total_requests = self._queue_stats['total_requests']

        if total_requests == 1:
            self._queue_stats['average_wait_time'] = wait_time
        else:
            # Weighted average (more weight to recent requests)
            self._queue_stats['average_wait_time'] = (current_avg * 0.8) + (wait_time * 0.2)

    async def _cleanup_stale_connections(self):
        """Remove stale connections from the pool async."""
        self._last_cleanup = time.time()

        # Test and remove dead connections
        alive_clients = []
        for client in self._pool:
            try:
                await asyncio.to_thread(client.ping)
                alive_clients.append(client)
            except (docker.errors.DockerException, OSError, RuntimeError) as e:
                logger.debug(f"Discarding dead connection during cleanup: {e}")  # Dead connection, discard

        self._pool = alive_clients
        logger.debug(f"Cleaned up pool: {len(alive_clients)} alive connections")

    def get_queue_stats(self) -> dict:
        """Get current queue statistics."""
        return {
            **self._queue_stats,
            'current_queue_size': self._queue.qsize(),
            'available_clients': len(self._pool),
            'clients_in_use': len(self._in_use),
            'max_connections': self._max_connections
        }

    async def close_all(self):
        """Close all connections in the pool async."""
        async with self._async_lock:
            for client in self._pool + self._in_use:
                try:
                    await asyncio.to_thread(client.close)
                except (OSError, RuntimeError, AttributeError) as e:
                    logger.debug(f"Error closing client during pool shutdown: {e}")
            self._pool.clear()
            self._in_use.clear()

        # Cancel queue processor
        if self._queue_processor_task:
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass
            self._queue_processor_task = None


# ============================================================================ #
# SERVICE FIRST GLOBAL SERVICE INSTANCE                                        #
# ============================================================================ #

# Global singleton service instance
_docker_client_service: Optional[DockerClientService] = None
_service_lock = threading.Lock()


def get_docker_client_service() -> DockerClientService:
    """
    Get the global Docker client service instance (SERVICE FIRST pattern).

    Returns:
        DockerClientService: Global singleton service instance
    """
    global _docker_client_service

    if _docker_client_service is None:
        with _service_lock:
            if _docker_client_service is None:
                _docker_client_service = DockerClientService()
                logger.info("Docker Client Service initialized (SERVICE FIRST)")

    return _docker_client_service


# ============================================================================ #
# BACKWARD COMPATIBILITY LAYER                                                 #
# ============================================================================ #

# Deprecated get_docker_pool() function removed - use get_docker_client_service() instead


# ============================================================================ #
# CONVENIENCE CONTEXT MANAGER FOR BACKWARD COMPATIBILITY                      #
# ============================================================================ #

@asynccontextmanager
async def get_docker_client_async(timeout: float = 30.0, operation: str = 'default', container_name: str = None):
    """
    Backward compatibility async context manager for Docker client access.
    FALLBACK: Uses simple docker.from_env() until SERVICE FIRST is fully stable.

    Args:
        timeout: Operation timeout in seconds
        operation: Operation type for optimization
        container_name: Container name for type-specific optimization

    Yields:
        docker.DockerClient: Docker client instance
    """
    # TEMPORARY FALLBACK: Use direct docker.from_env() for stability
    client = None
    try:
        # Load Docker configuration like the old working version
        from services.config.config_service import load_config
        config = load_config()
        docker_config = config.get('docker_config', {})
        socket_path = docker_config.get('docker_socket_path', '/var/run/docker.sock')

        try:
            # Method 1: Try configured socket path
            client = await asyncio.to_thread(
                docker.DockerClient,
                base_url=f'unix://{socket_path}',
                timeout=int(timeout)
            )
            await asyncio.to_thread(client.ping)
            logger.debug(f"Docker client created with configured socket: {socket_path}")

        except (docker.errors.DockerException, OSError, RuntimeError) as e1:
            logger.debug(f"Configured socket failed ({socket_path}): {e1}")
            try:
                # Method 2: Fallback to docker.from_env
                client = await asyncio.to_thread(docker.from_env, timeout=int(timeout))
                await asyncio.to_thread(client.ping)
                logger.debug("Docker client created with docker.from_env fallback")

            except (docker.errors.DockerException, OSError, RuntimeError) as e2:
                logger.error(f"All Docker client methods failed: config={e1}, from_env={e2}")
                raise DockerConnectionError(
                    "Docker connection failed",
                    error_code="DOCKER_CONNECTION_FAILED",
                    details={'config_error': str(e1), 'from_env_error': str(e2)}
                )

        yield client

    finally:
        if client:
            try:
                await asyncio.to_thread(client.close)
            except (OSError, RuntimeError, AttributeError):
                # Client close errors in finally block are non-critical
                pass
