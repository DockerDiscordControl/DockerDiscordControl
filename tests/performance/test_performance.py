# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Performance Tests                              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Performance tests using pytest-benchmark and custom performance monitoring.
Tests system performance under various load conditions.
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

from services.docker_service.docker_utils import get_docker_client, get_docker_client_pooled, USE_CONNECTION_POOL
from services.donation_management_service import DonationManagementService


@pytest.mark.performance
class TestDockerServicePerformance:
    """Performance tests for Docker service operations."""
    
    def setup_method(self):
        """Setup performance test fixtures."""
        self.service = DockerService()
        
        # Create mock containers for testing
        self.mock_containers = []
        for i in range(100):  # Large number for stress testing
            container = Mock()
            container.name = f"test_container_{i:03d}"
            container.status = "running" if i % 3 != 0 else "stopped"
            container.attrs = {
                "State": {
                    "Status": container.status,
                    "Running": container.status == "running"
                },
                "Config": {"Image": f"nginx:test_{i}"},
                "NetworkSettings": {"IPAddress": f"172.17.{i//256}.{i%256}"}
            }
            self.mock_containers.append(container)
    
    @pytest.mark.benchmark(group="docker-list")
    def test_get_containers_performance(self, benchmark):
        """Benchmark container listing performance."""
        with patch.object(self.service, '_get_docker_client') as mock_client:
            mock_docker = Mock()
            mock_docker.containers.list.return_value = self.mock_containers[:50]
            mock_client.return_value = mock_docker
            
            # Benchmark the operation
            result = benchmark(self.service.get_containers)
            
            assert result.success is True
            assert len(result.data) == 50
    
    @pytest.mark.benchmark(group="docker-operations")
    @pytest.mark.parametrize("container_count", [10, 50, 100])
    def test_multiple_container_operations_performance(self, benchmark, container_count):
        """Test performance with multiple container operations."""
        containers = self.mock_containers[:container_count]
        
        def perform_operations():
            operations = 0
            with patch.object(self.service, '_get_docker_client') as mock_client:
                mock_docker = Mock()
                mock_docker.containers.list.return_value = containers
                mock_docker.containers.get.return_value = containers[0] if containers else None
                mock_client.return_value = mock_docker
                
                # Simulate multiple operations
                for i in range(min(10, container_count)):  # Max 10 operations
                    result = self.service.get_container_by_name(f"test_container_{i:03d}")
                    if result.success:
                        operations += 1
                        
                return operations
        
        operations_completed = benchmark(perform_operations)
        assert operations_completed > 0
    
    def test_concurrent_docker_operations(self):
        """Test performance under concurrent load."""
        max_workers = 10
        operations_per_worker = 5
        
        def worker_task(worker_id):
            """Simulate worker performing Docker operations."""
            results = []
            with patch.object(self.service, '_get_docker_client') as mock_client:
                mock_docker = Mock()
                mock_docker.containers.list.return_value = self.mock_containers[:20]
                mock_client.return_value = mock_docker
                
                for i in range(operations_per_worker):
                    start_time = time.time()
                    result = self.service.get_containers()
                    end_time = time.time()
                    
                    results.append({
                        'worker_id': worker_id,
                        'operation_id': i,
                        'duration': end_time - start_time,
                        'success': result.success
                    })
            
            return results
        
        # Execute concurrent operations
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(worker_task, worker_id)
                for worker_id in range(max_workers)
            ]
            all_results = []
            for future in futures:
                all_results.extend(future.result())
        end_time = time.time()
        
        # Analyze results
        total_operations = len(all_results)
        successful_operations = sum(1 for r in all_results if r['success'])
        average_duration = sum(r['duration'] for r in all_results) / total_operations
        total_duration = end_time - start_time
        
        # Performance assertions
        assert successful_operations == total_operations  # All should succeed
        assert average_duration < 1.0  # Each operation should be under 1 second
        assert total_duration < 30.0  # Total test should complete in reasonable time
        
        # Calculate throughput
        throughput = total_operations / total_duration
        assert throughput > 1.0  # Should handle at least 1 operation per second
    
    @pytest.mark.benchmark(group="memory-usage")
    def test_memory_usage_with_large_container_list(self, benchmark):
        """Test memory usage when handling large numbers of containers."""
        large_container_list = self.mock_containers  # 100 containers
        
        def memory_intensive_operation():
            with patch.object(self.service, '_get_docker_client') as mock_client:
                mock_docker = Mock()
                mock_docker.containers.list.return_value = large_container_list
                mock_client.return_value = mock_docker
                
                # Perform multiple operations that might consume memory
                results = []
                for _ in range(10):  # Multiple calls
                    result = self.service.get_containers()
                    results.append(result.data if result.success else [])
                
                return len(results)
        
        # Monitor memory during the operation
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        operations_count = benchmark(memory_intensive_operation)
        
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # Memory usage assertions
        assert operations_count == 10
        # Memory increase should be reasonable (less than 100MB)
        assert memory_increase < 100 * 1024 * 1024  # 100MB
    
    def test_docker_service_scalability(self):
        """Test how the service scales with increasing container counts."""
        container_counts = [10, 50, 100, 200]
        performance_metrics = []
        
        for count in container_counts:
            containers = self.mock_containers[:count]
            
            with patch.object(self.service, '_get_docker_client') as mock_client:
                mock_docker = Mock()
                mock_docker.containers.list.return_value = containers
                mock_client.return_value = mock_docker
                
                # Measure performance
                start_time = time.time()
                for _ in range(5):  # 5 iterations for average
                    result = self.service.get_containers()
                    assert result.success
                end_time = time.time()
                
                avg_time = (end_time - start_time) / 5
                performance_metrics.append({
                    'container_count': count,
                    'avg_time': avg_time,
                    'containers_per_second': count / avg_time if avg_time > 0 else 0
                })
        
        # Performance should scale reasonably
        for metric in performance_metrics:
            # Should process at least 50 containers per second
            assert metric['containers_per_second'] > 50
            # Each operation should complete in reasonable time
            assert metric['avg_time'] < 2.0


@pytest.mark.performance
class TestWebUIPerformance:
    """Performance tests for Web UI components."""
    
    def setup_method(self):
        """Setup Web UI performance tests."""
        from app.web_ui import create_app
        self.app = create_app()
        self.client = self.app.test_client()
    
    @pytest.mark.benchmark(group="web-requests")
    def test_login_page_performance(self, benchmark):
        """Benchmark login page response time."""
        def load_login_page():
            with self.app.test_request_context():
                response = self.client.get('/login')
                return response.status_code
        
        status_code = benchmark(load_login_page)
        assert status_code == 200
    
    @pytest.mark.benchmark(group="web-requests")
    @patch('services.docker.docker_service.DockerService.get_containers')
    def test_dashboard_performance(self, mock_get_containers, benchmark):
        """Benchmark dashboard loading with various container counts."""
        # Mock container data
        mock_containers = []
        for i in range(50):  # Moderate number of containers
            container = Mock()
            container.name = f"container_{i}"
            container.status = "running"
            container.attrs = {
                "Config": {"Image": "nginx:latest"},
                "State": {"Status": "running"}
            }
            mock_containers.append(container)
        
        mock_get_containers.return_value = Mock(success=True, data=mock_containers)
        
        def load_dashboard():
            with self.app.test_request_context():
                # Mock authentication
                with patch('app.auth.verify_session', return_value=True):
                    response = self.client.get('/dashboard')
                    return response.status_code
        
        status_code = benchmark(load_dashboard)
        assert status_code in [200, 302]  # Success or redirect
    
    def test_concurrent_web_requests(self):
        """Test web UI performance under concurrent load."""
        max_workers = 20
        requests_per_worker = 10
        
        def worker_requests(worker_id):
            """Simulate worker making multiple requests."""
            results = []
            
            for i in range(requests_per_worker):
                start_time = time.time()
                response = self.client.get('/login')
                end_time = time.time()
                
                results.append({
                    'worker_id': worker_id,
                    'request_id': i,
                    'duration': end_time - start_time,
                    'status_code': response.status_code
                })
            
            return results
        
        # Execute concurrent requests
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(worker_requests, worker_id)
                for worker_id in range(max_workers)
            ]
            all_results = []
            for future in futures:
                all_results.extend(future.result())
        end_time = time.time()
        
        # Analyze results
        total_requests = len(all_results)
        successful_requests = sum(1 for r in all_results if r['status_code'] == 200)
        average_response_time = sum(r['duration'] for r in all_results) / total_requests
        total_duration = end_time - start_time
        
        # Performance assertions
        assert successful_requests >= total_requests * 0.95  # 95% success rate
        assert average_response_time < 1.0  # Average response under 1 second
        
        # Calculate requests per second
        rps = total_requests / total_duration
        assert rps > 10  # Should handle at least 10 RPS
    
    @pytest.mark.benchmark(group="api-endpoints")
    @patch('services.docker.docker_service.DockerService.get_container_by_name')
    def test_api_endpoint_performance(self, mock_get_container, benchmark):
        """Benchmark API endpoint performance."""
        # Mock container response
        mock_container = Mock()
        mock_container.name = "test_container"
        mock_container.status = "running"
        mock_get_container.return_value = Mock(success=True, data=mock_container)
        
        def api_request():
            with self.app.test_request_context():
                response = self.client.post('/api/container/info', 
                                          json={'container_name': 'test_container'})
                return response.status_code
        
        status_code = benchmark(api_request)
        assert status_code in [200, 401, 403]  # Valid responses


@pytest.mark.performance
class TestDonationSystemPerformance:
    """Performance tests for donation system."""
    
    def setup_method(self):
        """Setup donation system performance tests."""
        self.service = DonationManagementService()
    
    @pytest.mark.benchmark(group="donation-operations")
    @patch('services.donation.donation_management_service.get_mech_service')
    def test_donation_history_performance(self, mock_get_mech_service, benchmark):
        """Benchmark donation history retrieval performance."""
        # Mock large donation history
        donations = []
        for i in range(1000):  # Large number of donations
            donations.append({
                'username': f'user_{i}',
                'amount': 10.0 + (i % 100),
                'ts': f'2025-01-01T{i%24:02d}:00:00Z'
            })
        
        mock_mech_service = Mock()
        mock_state = Mock()
        mock_state.total_donated = sum(d['amount'] for d in donations)
        mock_mech_service.get_state.return_value = mock_state
        mock_mech_service.store.load.return_value = {'donations': donations}
        mock_get_mech_service.return_value = mock_mech_service
        
        def get_donation_history():
            result = self.service.get_donation_history(limit=100)
            return result.success
        
        success = benchmark(get_donation_history)
        assert success is True
    
    @pytest.mark.benchmark(group="donation-stats")
    @patch('services.donation.donation_management_service.get_mech_service')
    def test_donation_stats_calculation_performance(self, mock_get_mech_service, benchmark):
        """Benchmark donation statistics calculation."""
        # Mock large dataset
        donations = [{'amount': 10.0 + (i % 100)} for i in range(5000)]
        
        mock_mech_service = Mock()
        mock_state = Mock()
        mock_state.total_donated = 275000.0  # Approximate total
        mock_mech_service.get_state.return_value = mock_state
        mock_mech_service.store.load.return_value = {'donations': donations}
        mock_get_mech_service.return_value = mock_mech_service
        
        def calculate_stats():
            result = self.service.get_donation_stats()
            return result.success
        
        success = benchmark(calculate_stats)
        assert success is True


@pytest.mark.performance 
@pytest.mark.slow
class TestSystemResourceUsage:
    """Test system resource usage under load."""
    
    def test_cpu_usage_under_load(self):
        """Test CPU usage during intensive operations."""
        initial_cpu = psutil.cpu_percent(interval=1)
        
        # Simulate CPU-intensive work
        service = DockerService()
        
        with patch.object(service, '_get_docker_client') as mock_client:
            # Create large mock container list
            containers = [Mock() for _ in range(1000)]
            for i, container in enumerate(containers):
                container.name = f"container_{i}"
                container.status = "running"
                container.attrs = {"State": {"Status": "running"}}
            
            mock_docker = Mock()
            mock_docker.containers.list.return_value = containers
            mock_client.return_value = mock_docker
            
            # Perform intensive operations
            start_time = time.time()
            for _ in range(100):  # Many operations
                result = service.get_containers()
                assert result.success
            end_time = time.time()
        
        final_cpu = psutil.cpu_percent(interval=1)
        operation_time = end_time - start_time
        
        # CPU usage should be reasonable
        cpu_increase = final_cpu - initial_cpu
        assert cpu_increase < 80  # Should not max out CPU
        assert operation_time < 30  # Should complete in reasonable time
    
    def test_memory_leak_detection(self):
        """Test for memory leaks during repeated operations."""
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        service = DockerService()
        
        # Perform many operations to detect potential leaks
        for iteration in range(50):  # Many iterations
            with patch.object(service, '_get_docker_client') as mock_client:
                containers = [Mock() for _ in range(100)]
                for i, container in enumerate(containers):
                    container.name = f"container_{i}_{iteration}"
                    container.status = "running"
                
                mock_docker = Mock()
                mock_docker.containers.list.return_value = containers
                mock_client.return_value = mock_docker
                
                result = service.get_containers()
                assert result.success
                
                # Check memory every 10 iterations
                if iteration % 10 == 0:
                    current_memory = process.memory_info().rss
                    memory_increase = current_memory - initial_memory
                    
                    # Memory increase should be bounded
                    # Allow some increase but not excessive
                    max_allowed_increase = 50 * 1024 * 1024  # 50MB
                    assert memory_increase < max_allowed_increase
        
        final_memory = process.memory_info().rss
        total_memory_increase = final_memory - initial_memory
        
        # Total memory increase should be reasonable
        assert total_memory_increase < 100 * 1024 * 1024  # 100MB max


# Performance test utilities
def measure_execution_time(func, *args, **kwargs):
    """Utility to measure function execution time."""
    start_time = time.time()
    result = func(*args, **kwargs)
    end_time = time.time()
    return result, end_time - start_time


def profile_memory_usage(func, *args, **kwargs):
    """Utility to profile memory usage of a function."""
    import tracemalloc
    
    tracemalloc.start()
    
    # Take snapshot before
    snapshot_before = tracemalloc.take_snapshot()
    
    # Execute function
    result = func(*args, **kwargs)
    
    # Take snapshot after
    snapshot_after = tracemalloc.take_snapshot()
    
    # Compare snapshots
    top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')
    
    tracemalloc.stop()
    
    return result, top_stats


# Custom pytest configuration for performance tests
def pytest_configure(config):
    """Configure pytest for performance tests."""
    config.addinivalue_line(
        "markers",
        "performance: mark test as performance test"
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow running performance test"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])