# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Docker Pool Performance Tests                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Performance tests for Docker Client Pool vs Legacy Client implementation.
Tests connection reuse, concurrency performance, and resource efficiency.
"""

import pytest
import time
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
import resource
import psutil
import os
from typing import List, Dict, Any

# Import both implementations for comparison
from services.docker_service.docker_utils import get_docker_client, get_docker_client_pooled, USE_CONNECTION_POOL
from services.docker_service.docker_client_pool import get_docker_pool, DockerClientPool


@pytest.mark.performance
class TestDockerPoolPerformance:
    """Performance tests comparing Docker Pool vs Legacy implementation."""
    
    def setup_method(self):
        """Setup performance test fixtures."""
        self.iterations = 50
        self.concurrent_threads = 10
        
        # Reset pool for clean tests
        if USE_CONNECTION_POOL:
            pool = get_docker_pool()
            pool.close_all()
    
    @pytest.mark.benchmark(group="docker-client")
    @pytest.mark.skipif(not USE_CONNECTION_POOL, reason="Connection pool not available")
    def test_pooled_client_performance(self, benchmark):
        """Benchmark pooled Docker client acquisition."""
        def get_pooled_client():
            with get_docker_client_pooled() as client:
                # Simulate minimal Docker operation
                return type(client).__name__
        
        with patch('docker.from_env') as mock_docker_env:
            mock_client = Mock()
            mock_client.ping.return_value = True
            mock_docker_env.return_value = mock_client
            
            result = benchmark(get_pooled_client)
            assert result is not None
    
    @pytest.mark.benchmark(group="docker-client")
    def test_legacy_client_performance(self, benchmark):
        """Benchmark legacy Docker client acquisition."""
        def get_legacy_client():
            client = get_docker_client()
            if client:
                return type(client).__name__
            return None
        
        with patch('docker.from_env') as mock_docker_env:
            mock_client = Mock()
            mock_client.ping.return_value = True
            mock_docker_env.return_value = mock_client
            
            result = benchmark(get_legacy_client)
            # Legacy might return None in test environment
    
    @pytest.mark.skipif(not USE_CONNECTION_POOL, reason="Connection pool not available")
    def test_concurrent_pool_performance(self):
        """Test connection pool performance under concurrent load."""
        results = []
        errors = []
        
        def worker_task(worker_id):
            try:
                start_time = time.time()
                with get_docker_client_pooled() as client:
                    # Simulate work
                    time.sleep(0.01)  # 10ms simulated work
                duration = time.time() - start_time
                results.append({
                    'worker_id': worker_id,
                    'duration': duration,
                    'client_type': type(client).__name__ if client else 'None'
                })
            except Exception as e:
                errors.append(f"Worker {worker_id}: {e}")
        
        with patch('docker.from_env') as mock_docker_env:
            mock_client = Mock()
            mock_client.ping.return_value = True
            mock_docker_env.return_value = mock_client
            
            # Run concurrent workers
            with ThreadPoolExecutor(max_workers=self.concurrent_threads) as executor:
                futures = [executor.submit(worker_task, i) for i in range(self.iterations)]
                for future in futures:
                    future.result(timeout=30)  # Wait for completion
        
        # Analyze results
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == self.iterations
        
        avg_duration = sum(r['duration'] for r in results) / len(results)
        max_duration = max(r['duration'] for r in results)
        
        # Performance assertions (these may need adjustment based on environment)
        assert avg_duration < 0.1, f"Average duration too high: {avg_duration:.3f}s"
        assert max_duration < 0.2, f"Max duration too high: {max_duration:.3f}s"
        
        print(f"\nPool Performance Results:")
        print(f"- Workers: {self.iterations}")
        print(f"- Average duration: {avg_duration:.3f}s")
        print(f"- Max duration: {max_duration:.3f}s")
        print(f"- Errors: {len(errors)}")
    
    @pytest.mark.skipif(not USE_CONNECTION_POOL, reason="Connection pool not available")
    def test_pool_connection_reuse(self):
        """Test that the pool actually reuses connections."""
        with patch('docker.from_env') as mock_docker_env:
            mock_clients = []
            
            def create_mock_client():
                mock_client = Mock()
                mock_client.ping.return_value = True
                mock_clients.append(mock_client)
                return mock_client
            
            mock_docker_env.side_effect = create_mock_client
            
            # Get pool and perform multiple operations
            pool = get_docker_pool()
            
            # First round of clients
            client1 = None
            client2 = None
            with pool.get_client() as c1:
                client1 = c1
                with pool.get_client() as c2:
                    client2 = c2
            
            # Second round - should reuse connections
            client3 = None
            client4 = None
            with pool.get_client() as c3:
                client3 = c3
                with pool.get_client() as c4:
                    client4 = c4
            
            # Check that we didn't create too many clients
            # With pool size 3, we should create max 3 clients for this test
            assert len(mock_clients) <= 3, f"Too many clients created: {len(mock_clients)}"
            
            print(f"\nConnection Reuse Test:")
            print(f"- Mock clients created: {len(mock_clients)}")
            print(f"- Pool max connections: {pool._max_connections}")
    
    def test_resource_usage_comparison(self):
        """Compare resource usage between pool and legacy implementation."""
        if not USE_CONNECTION_POOL:
            pytest.skip("Connection pool not available")
        
        process = psutil.Process()
        
        # Test legacy implementation
        with patch('docker.from_env') as mock_docker_env:
            mock_client = Mock()
            mock_client.ping.return_value = True
            mock_docker_env.return_value = mock_client
            
            # Baseline measurement
            baseline_memory = process.memory_info().rss
            baseline_threads = process.num_threads()
            
            # Legacy client test
            legacy_start = time.time()
            for i in range(10):
                client = get_docker_client()
                if client:
                    # Simulate some work
                    pass
            legacy_duration = time.time() - legacy_start
            legacy_memory = process.memory_info().rss
            legacy_threads = process.num_threads()
            
            # Pool client test  
            pool = get_docker_pool()
            pool.close_all()  # Reset pool
            
            pool_start = time.time()
            for i in range(10):
                with pool.get_client() as client:
                    # Simulate some work
                    pass
            pool_duration = time.time() - pool_start
            pool_memory = process.memory_info().rss
            pool_threads = process.num_threads()
        
        print(f"\nResource Usage Comparison:")
        print(f"- Legacy duration: {legacy_duration:.3f}s")
        print(f"- Pool duration: {pool_duration:.3f}s")
        print(f"- Memory delta (legacy): {(legacy_memory - baseline_memory) / 1024:.1f}KB")
        print(f"- Memory delta (pool): {(pool_memory - baseline_memory) / 1024:.1f}KB") 
        print(f"- Thread delta (legacy): {legacy_threads - baseline_threads}")
        print(f"- Thread delta (pool): {pool_threads - baseline_threads}")
        
        # Pool should be faster or comparable
        # Note: In test environment with mocks, timing differences may be minimal