# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Docker Async Queue Performance Tests          #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Performance tests for Docker Async Queue System v3.0.
Tests queue performance, concurrency handling, and timeout management.
"""

import pytest
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch, AsyncMock
import psutil
import os

# Import modern async API
from services.docker_service.docker_utils import (
    get_docker_client_async,
    get_container_status_async,
    execute_container_action_async
)


@pytest.mark.performance
@pytest.mark.asyncio
class TestDockerAsyncQueuePerformance:
    """Performance tests for Docker Async Queue System."""

    @pytest.mark.benchmark(group="docker-async-client")
    async def test_async_client_acquisition_performance(self, benchmark):
        """Benchmark async Docker client acquisition."""
        async def get_async_client():
            async with get_docker_client_async() as client:
                return type(client).__name__ if client else 'None'

        with patch('aiodocker.Docker') as mock_docker:
            mock_client = AsyncMock()
            mock_client.ping.return_value = True
            mock_docker.return_value = mock_client

            result = await benchmark.pedantic(
                get_async_client,
                iterations=10,
                rounds=5
            )
            assert result is not None

    @pytest.mark.asyncio
    async def test_concurrent_async_operations(self):
        """Test async queue performance under concurrent load."""
        max_workers = 20
        operations_per_worker = 10
        results = []

        async def worker_task(worker_id):
            """Simulate worker performing async Docker operations."""
            worker_results = []

            for i in range(operations_per_worker):
                start_time = time.time()

                try:
                    async with get_docker_client_async(timeout=30.0) as client:
                        # Simulate minimal work
                        await asyncio.sleep(0.01)  # 10ms simulated work

                    duration = time.time() - start_time
                    worker_results.append({
                        'worker_id': worker_id,
                        'operation_id': i,
                        'duration': duration,
                        'success': True
                    })
                except Exception as e:
                    worker_results.append({
                        'worker_id': worker_id,
                        'operation_id': i,
                        'duration': 0,
                        'success': False,
                        'error': str(e)
                    })

            return worker_results

        with patch('aiodocker.Docker') as mock_docker:
            mock_client = AsyncMock()
            mock_client.ping.return_value = True
            mock_client.close.return_value = None
            mock_docker.return_value = mock_client

            # Run concurrent workers
            start_time = time.time()
            tasks = [worker_task(i) for i in range(max_workers)]
            all_worker_results = await asyncio.gather(*tasks)
            end_time = time.time()

            # Flatten results
            for worker_results in all_worker_results:
                results.extend(worker_results)

        # Analyze results
        total_operations = len(results)
        successful_operations = sum(1 for r in results if r['success'])
        failed_operations = total_operations - successful_operations
        average_duration = sum(r['duration'] for r in results if r['success']) / successful_operations if successful_operations > 0 else 0
        total_duration = end_time - start_time

        # Performance assertions
        assert successful_operations >= total_operations * 0.95  # 95% success rate
        assert average_duration < 0.5  # Each operation should be under 500ms
        assert total_duration < 60.0  # Total test should complete in reasonable time

        # Calculate throughput
        throughput = total_operations / total_duration

        print(f"\nAsync Queue Performance Results:")
        print(f"- Total operations: {total_operations}")
        print(f"- Successful: {successful_operations}")
        print(f"- Failed: {failed_operations}")
        print(f"- Average duration: {average_duration:.3f}s")
        print(f"- Total duration: {total_duration:.3f}s")
        print(f"- Throughput: {throughput:.2f} ops/sec")

    @pytest.mark.asyncio
    async def test_queue_stress_test(self):
        """Stress test the async queue with many concurrent requests."""
        concurrent_requests = 50

        async def make_request(request_id):
            start_time = time.time()
            try:
                async with get_docker_client_async(timeout=30.0) as client:
                    await asyncio.sleep(0.001)  # 1ms work
                return {
                    'id': request_id,
                    'duration': time.time() - start_time,
                    'success': True
                }
            except Exception as e:
                return {
                    'id': request_id,
                    'duration': time.time() - start_time,
                    'success': False,
                    'error': str(e)
                }

        with patch('aiodocker.Docker') as mock_docker:
            mock_client = AsyncMock()
            mock_client.ping.return_value = True
            mock_client.close.return_value = None
            mock_docker.return_value = mock_client

            start_time = time.time()
            results = await asyncio.gather(*[make_request(i) for i in range(concurrent_requests)])
            total_duration = time.time() - start_time

        successful = sum(1 for r in results if r['success'])
        avg_duration = sum(r['duration'] for r in results) / len(results)

        print(f"\nQueue Stress Test Results:")
        print(f"- Concurrent requests: {concurrent_requests}")
        print(f"- Successful: {successful}")
        print(f"- Success rate: {successful/concurrent_requests*100:.1f}%")
        print(f"- Average duration: {avg_duration:.3f}s")
        print(f"- Total duration: {total_duration:.3f}s")

        # At least 90% should succeed
        assert successful >= concurrent_requests * 0.9

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="container-status")
    async def test_container_status_performance(self, benchmark):
        """Benchmark container status retrieval."""
        async def get_status():
            return await get_container_status_async('test_container')

        with patch('aiodocker.Docker') as mock_docker:
            mock_client = AsyncMock()
            mock_container = Mock()
            mock_container.show.return_value = {
                'Name': '/test_container',
                'State': {'Status': 'running', 'Running': True},
                'Config': {'Image': 'nginx:latest'}
            }
            mock_client.containers.get.return_value = mock_container
            mock_client.close.return_value = None
            mock_docker.return_value = mock_client

            result = await benchmark.pedantic(
                get_status,
                iterations=10,
                rounds=5
            )

    @pytest.mark.asyncio
    @pytest.mark.benchmark(group="container-action")
    async def test_container_action_performance(self, benchmark):
        """Benchmark container action execution."""
        async def execute_action():
            return await execute_container_action_async('test_container', 'restart')

        with patch('aiodocker.Docker') as mock_docker:
            mock_client = AsyncMock()
            mock_container = AsyncMock()
            mock_container.restart.return_value = None
            mock_client.containers.get.return_value = mock_container
            mock_client.close.return_value = None
            mock_docker.return_value = mock_client

            result = await benchmark.pedantic(
                execute_action,
                iterations=5,
                rounds=3
            )

    @pytest.mark.asyncio
    async def test_timeout_handling_performance(self):
        """Test performance of timeout handling."""
        timeout_values = [10.0, 30.0, 60.0]
        results = []

        for timeout in timeout_values:
            async def timed_operation():
                start = time.time()
                try:
                    async with get_docker_client_async(timeout=timeout) as client:
                        await asyncio.sleep(0.01)
                    return time.time() - start
                except asyncio.TimeoutError:
                    return None

            with patch('aiodocker.Docker') as mock_docker:
                mock_client = AsyncMock()
                mock_client.close.return_value = None
                mock_docker.return_value = mock_client

                duration = await timed_operation()
                results.append({
                    'timeout': timeout,
                    'duration': duration
                })

        print(f"\nTimeout Handling Results:")
        for r in results:
            print(f"- Timeout {r['timeout']}s: Duration {r['duration']:.3f}s" if r['duration'] else f"- Timeout {r['timeout']}s: Timed out")

    @pytest.mark.asyncio
    async def test_memory_usage_async_operations(self):
        """Test memory usage during async operations."""
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        iterations = 100

        with patch('aiodocker.Docker') as mock_docker:
            mock_client = AsyncMock()
            mock_client.close.return_value = None
            mock_docker.return_value = mock_client

            async def perform_operations():
                for i in range(iterations):
                    async with get_docker_client_async() as client:
                        await asyncio.sleep(0.001)

            await perform_operations()

        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        print(f"\nMemory Usage Test:")
        print(f"- Iterations: {iterations}")
        print(f"- Initial memory: {initial_memory / 1024 / 1024:.2f}MB")
        print(f"- Final memory: {final_memory / 1024 / 1024:.2f}MB")
        print(f"- Increase: {memory_increase / 1024 / 1024:.2f}MB")

        # Memory increase should be reasonable (less than 50MB for 100 iterations)
        assert memory_increase < 50 * 1024 * 1024


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])
