# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Docker API Integration Tests                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Integration tests for Docker API functionality.
Tests real Docker daemon integration with mock containers for safety.
"""

import pytest
import docker
import time
from unittest.mock import Mock, patch, MagicMock
from testcontainers.compose import DockerCompose

from services.docker.docker_service import DockerService, ServiceResult
from cogs.docker_control import DockerControlCog


@pytest.mark.integration
@pytest.mark.docker
class TestDockerServiceIntegration:
    """Integration tests for DockerService with real Docker daemon."""
    
    @classmethod
    def setup_class(cls):
        """Setup test class with Docker client."""
        try:
            cls.docker_client = docker.from_env()
            cls.docker_client.ping()
        except Exception as e:
            pytest.skip(f"Docker daemon not available: {e}")
    
    def setup_method(self):
        """Setup test fixtures for each test method."""
        self.service = DockerService()
        self.test_containers = []
    
    def teardown_method(self):
        """Cleanup after each test."""
        # Clean up any test containers
        for container in self.test_containers:
            try:
                container.stop(timeout=1)
                container.remove(force=True)
            except:
                pass
    
    def test_get_containers_real_docker(self):
        """Test retrieving containers from real Docker daemon."""
        result = self.service.get_containers()
        
        assert result.success is True
        assert isinstance(result.data, list)
        
        # Should return container objects with expected attributes
        for container in result.data:
            assert hasattr(container, 'name')
            assert hasattr(container, 'status')
            assert hasattr(container, 'attrs')
    
    def test_container_lifecycle_with_test_container(self):
        """Test complete container lifecycle with a test container."""
        # Create a test container
        test_container = self.docker_client.containers.run(
            'alpine:latest',
            'sleep 30',
            name='ddc_test_container',
            detach=True,
            remove=False
        )
        self.test_containers.append(test_container)
        
        # Test get_container_by_name
        result = self.service.get_container_by_name('ddc_test_container')
        assert result.success is True
        assert result.data.name == 'ddc_test_container'
        assert result.data.status == 'running'
        
        # Test stop_container
        stop_result = self.service.stop_container('ddc_test_container')
        assert stop_result.success is True
        
        # Wait a moment for Docker to update status
        time.sleep(1)
        
        # Verify container is stopped
        stopped_result = self.service.get_container_by_name('ddc_test_container')
        assert stopped_result.success is True
        assert stopped_result.data.status in ['stopped', 'exited']
        
        # Test start_container
        start_result = self.service.start_container('ddc_test_container')
        assert start_result.success is True
        
        # Wait a moment for Docker to update status
        time.sleep(1)
        
        # Verify container is running
        running_result = self.service.get_container_by_name('ddc_test_container')
        assert running_result.success is True
        assert running_result.data.status == 'running'
        
        # Test restart_container
        restart_result = self.service.restart_container('ddc_test_container')
        assert restart_result.success is True
    
    def test_container_not_found(self):
        """Test handling of non-existent containers."""
        result = self.service.get_container_by_name('nonexistent_container_12345')
        
        assert result.success is False
        assert "not found" in result.error.lower()
    
    def test_get_container_stats_real(self):
        """Test getting real container statistics."""
        # Create a test container
        test_container = self.docker_client.containers.run(
            'alpine:latest',
            'sleep 10',
            name='ddc_stats_test',
            detach=True,
            remove=False
        )
        self.test_containers.append(test_container)
        
        # Wait a moment for container to start
        time.sleep(2)
        
        result = self.service.get_container_stats('ddc_stats_test')
        
        if result.success:
            stats = result.data
            # Check that we have basic stat fields
            assert 'cpu_percent' in stats or 'memory_usage' in stats
        else:
            # Stats might not be available immediately, that's okay
            assert "stats" in result.error.lower()
    
    def test_get_container_logs_real(self):
        """Test getting real container logs."""
        # Create a container that produces logs
        test_container = self.docker_client.containers.run(
            'alpine:latest',
            'sh -c "echo Hello World; echo Test Log; sleep 5"',
            name='ddc_logs_test',
            detach=True,
            remove=False
        )
        self.test_containers.append(test_container)
        
        # Wait for logs to be generated
        time.sleep(2)
        
        result = self.service.get_container_logs('ddc_logs_test', lines=10)
        
        assert result.success is True
        logs = result.data
        assert isinstance(logs, str)
        assert len(logs) > 0
    
    @patch('services.docker.docker_service.docker.from_env')
    def test_docker_connection_error_handling(self, mock_docker_from_env):
        """Test handling of Docker connection errors."""
        # Mock Docker client to raise connection error
        mock_docker_from_env.side_effect = docker.errors.DockerException("Connection failed")
        
        # Create new service instance to trigger connection attempt
        service = DockerService()
        result = service.get_containers()
        
        assert result.success is False
        assert "docker" in result.error.lower()
    
    def test_container_operations_error_handling(self):
        """Test error handling for container operations."""
        # Try to operate on non-existent container
        stop_result = self.service.stop_container('definitely_does_not_exist_12345')
        assert stop_result.success is False
        
        start_result = self.service.start_container('definitely_does_not_exist_12345')
        assert start_result.success is False
        
        restart_result = self.service.restart_container('definitely_does_not_exist_12345')
        assert restart_result.success is False


@pytest.mark.integration
@pytest.mark.docker
class TestDockerControlCogIntegration:
    """Integration tests for DockerControlCog with real Docker."""
    
    @classmethod
    def setup_class(cls):
        """Setup test class."""
        try:
            cls.docker_client = docker.from_env()
            cls.docker_client.ping()
        except Exception as e:
            pytest.skip(f"Docker daemon not available: {e}")
    
    def setup_method(self):
        """Setup test fixtures."""
        # Mock bot
        self.mock_bot = Mock()
        self.cog = DockerControlCog(self.mock_bot)
        self.test_containers = []
    
    def teardown_method(self):
        """Cleanup after each test."""
        for container in self.test_containers:
            try:
                container.stop(timeout=1)
                container.remove(force=True)
            except:
                pass
    
    @pytest.mark.asyncio
    async def test_info_command_with_real_container(self):
        """Test /info command with a real test container."""
        # Create test container
        test_container = self.docker_client.containers.run(
            'nginx:alpine',
            name='ddc_info_test',
            detach=True,
            remove=False,
            ports={'80/tcp': None}  # Random port
        )
        self.test_containers.append(test_container)
        
        # Wait for container to start
        time.sleep(2)
        
        # Mock Discord context
        mock_ctx = Mock()
        mock_ctx.guild_id = 123456789
        mock_ctx.user.id = 111222333
        mock_ctx.respond = Mock(return_value=None)
        mock_ctx.interaction.response.is_done.return_value = False
        
        # Mock permissions and config
        with patch.multiple(
            self.cog,
            check_permissions=Mock(return_value=True),
            get_spam_protection_service=Mock(return_value=Mock(
                check_user_cooldown=Mock(return_value=Mock(
                    success=True,
                    data={'in_cooldown': False, 'remaining_time': 0}
                )),
                set_user_cooldown=Mock(return_value=Mock(success=True))
            )),
            get_config_service=Mock(return_value=Mock(
                get_config=Mock(return_value={'container_info': {}})
            ))
        ):
            # Test the info command
            await self.cog.info_command(mock_ctx, 'ddc_info_test')
        
        # Verify response was called
        mock_ctx.respond.assert_called_once()
        call_args = mock_ctx.respond.call_args
        
        # Should have embed and view
        assert 'embed' in call_args.kwargs
        assert 'view' in call_args.kwargs
    
    @pytest.mark.asyncio
    async def test_info_command_nonexistent_container(self):
        """Test /info command with nonexistent container."""
        mock_ctx = Mock()
        mock_ctx.guild_id = 123456789
        mock_ctx.user.id = 111222333
        mock_ctx.respond = Mock(return_value=None)
        mock_ctx.interaction.response.is_done.return_value = False
        
        with patch.multiple(
            self.cog,
            check_permissions=Mock(return_value=True),
            get_spam_protection_service=Mock(return_value=Mock(
                check_user_cooldown=Mock(return_value=Mock(
                    success=True,
                    data={'in_cooldown': False, 'remaining_time': 0}
                ))
            ))
        ):
            await self.cog.info_command(mock_ctx, 'nonexistent_container')
        
        # Should still respond (with error message)
        mock_ctx.respond.assert_called_once()
        
        # Check if response contains error indication
        call_args = mock_ctx.respond.call_args
        embed = call_args.kwargs.get('embed')
        if embed:
            # Error should be indicated in embed
            assert embed.color.value != 0x00ff00  # Not green (success)


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.slow
class TestDockerPerformanceWithMultipleContainers:
    """Performance tests with multiple containers."""
    
    @classmethod
    def setup_class(cls):
        """Setup test class."""
        try:
            cls.docker_client = docker.from_env()
            cls.docker_client.ping()
        except Exception as e:
            pytest.skip(f"Docker daemon not available: {e}")
    
    def setup_method(self):
        """Setup test fixtures."""
        self.service = DockerService()
        self.test_containers = []
    
    def teardown_method(self):
        """Cleanup after each test."""
        for container in self.test_containers:
            try:
                container.stop(timeout=1)
                container.remove(force=True)
            except:
                pass
    
    @pytest.mark.parametrize("container_count", [5, 10])
    def test_get_containers_performance(self, container_count):
        """Test performance of getting multiple containers."""
        # Create multiple test containers
        for i in range(container_count):
            container = self.docker_client.containers.run(
                'alpine:latest',
                'sleep 30',
                name=f'ddc_perf_test_{i}',
                detach=True,
                remove=False
            )
            self.test_containers.append(container)
        
        # Measure time to get all containers
        start_time = time.time()
        result = self.service.get_containers()
        end_time = time.time()
        
        assert result.success is True
        execution_time = end_time - start_time
        
        # Should be reasonably fast even with multiple containers
        assert execution_time < 5.0  # 5 seconds max
        
        # Should return at least our test containers
        container_names = [c.name for c in result.data]
        test_container_names = [f'ddc_perf_test_{i}' for i in range(container_count)]
        
        for test_name in test_container_names:
            assert test_name in container_names
    
    def test_concurrent_container_operations(self):
        """Test concurrent operations on multiple containers."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        # Create test containers
        for i in range(3):
            container = self.docker_client.containers.run(
                'alpine:latest',
                'sleep 60',
                name=f'ddc_concurrent_test_{i}',
                detach=True,
                remove=False
            )
            self.test_containers.append(container)
        
        def stop_and_start_container(container_name):
            """Helper function to stop and start a container."""
            stop_result = self.service.stop_container(container_name)
            if stop_result.success:
                time.sleep(1)  # Wait for stop
                start_result = self.service.start_container(container_name)
                return start_result.success
            return False
        
        # Test concurrent operations
        container_names = [f'ddc_concurrent_test_{i}' for i in range(3)]
        
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(stop_and_start_container, name)
                for name in container_names
            ]
            results = [future.result() for future in futures]
        end_time = time.time()
        
        # All operations should succeed
        assert all(results)
        
        # Concurrent operations should be reasonably fast
        assert end_time - start_time < 10.0


@pytest.mark.integration
@pytest.mark.docker
class TestDockerComposeIntegration:
    """Integration tests using docker-compose for complex scenarios."""
    
    def test_with_docker_compose_stack(self):
        """Test Docker operations with a compose stack."""
        compose_content = """
version: '3.8'
services:
  test-web:
    image: nginx:alpine
    ports:
      - "0:80"
  test-db:
    image: postgres:13-alpine
    environment:
      POSTGRES_DB: testdb
      POSTGRES_USER: testuser
      POSTGRES_PASSWORD: testpass
"""
        
        with DockerCompose(".", compose_file_name="test-compose.yml") as compose:
            # Write compose file
            with open("test-compose.yml", "w") as f:
                f.write(compose_content)
            
            # Wait for services to start
            time.sleep(5)
            
            # Test our service can find the containers
            service = DockerService()
            result = service.get_containers()
            
            assert result.success is True
            
            # Find our test containers
            container_names = [c.name for c in result.data]
            test_containers = [name for name in container_names if 'test-' in name]
            
            assert len(test_containers) >= 2  # Should find web and db
    
    @pytest.mark.skipif(
        not pytest.config.getoption("--run-expensive"),
        reason="Expensive test, run with --run-expensive"
    )
    def test_docker_service_with_resource_constraints(self):
        """Test Docker service behavior under resource constraints."""
        # This test would create containers with specific resource limits
        # and test how our service handles them
        pytest.skip("Expensive test - implement if needed")


# Custom pytest configuration for Docker tests
def pytest_configure(config):
    """Configure pytest for Docker integration tests."""
    config.addinivalue_line(
        "markers", 
        "docker: mark test as requiring Docker daemon"
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow running"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to skip Docker tests if Docker not available."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
    except:
        skip_docker = pytest.mark.skip(reason="Docker daemon not available")
        for item in items:
            if "docker" in item.keywords:
                item.add_marker(skip_docker)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])