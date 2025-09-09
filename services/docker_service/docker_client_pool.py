# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Docker Client Connection Pool                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Optimized Docker client connection pooling for better performance.
Reuses connections instead of creating new ones for each request.
"""

import docker
import threading
import time
import logging
import asyncio
from typing import Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass

logger = logging.getLogger('ddc.docker_pool')


@dataclass
class QueueRequest:
    """Represents a queued client request."""
    request_id: str
    timestamp: float
    timeout: float
    future: asyncio.Future


class DockerClientPool:
    """Async Docker client connection pool with intelligent queue system."""
    
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
                    except Exception as e:
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
            except Exception as e:
                logger.error(f"Error in queue processor: {e}")
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
        except Exception as e:
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
                except Exception as e:
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
                except Exception as e:
                    logger.debug(f"Dead connection in queue acquisition: {e}")
                    self._in_use.remove(client)
                    # Continue to try creating a new client
            
            # Check if we can create new client
            if len(self._in_use) < self._max_connections:
                return await self._create_new_client_async()
            
            # Pool is full, return None to signal queue processor to wait
            return None
    
    async def _create_new_client_async(self) -> docker.DockerClient:
        """Create a new Docker client async."""
        client = await asyncio.to_thread(docker.from_env)
        self._in_use.append(client)
        return client
    
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
            except Exception as e:
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
                except Exception as e:
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


# Global singleton pool
_docker_pool = None
_pool_lock = threading.Lock()


def get_docker_pool() -> DockerClientPool:
    """Get the global Docker client pool."""
    global _docker_pool
    
    if _docker_pool is None:
        with _pool_lock:
            if _docker_pool is None:
                _docker_pool = DockerClientPool()
    
    return _docker_pool


# Modern async-only API
# All functions now use pool.get_client_async() for optimal performance