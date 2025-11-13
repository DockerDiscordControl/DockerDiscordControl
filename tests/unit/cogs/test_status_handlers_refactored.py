#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for StatusHandlersMixin - Post-Refactoring Tests

Tests for new functionality introduced during refactoring:
1. ContainerStatusResult return type (replaces tuples)
2. bulk_fetch_container_status with intelligent batching
3. Pending status handling with action-aware logic
4. Performance profiling integration

These tests ensure the refactored implementation works correctly.
"""
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

# Import the class we're testing
from cogs.status_handlers import StatusHandlersMixin
from services.docker_status import (
    get_performance_service,
    get_fetch_service,
    ContainerStatusResult
)
from services.discord import get_conditional_cache_service


class MockBot:
    """Mock Discord bot for testing"""
    def __init__(self):
        self.user = Mock()
        self.user.id = 123456789

    def get_channel(self, channel_id):
        """Mock get_channel"""
        return None


class TestContainerStatusResult:
    """Tests for ContainerStatusResult dataclass"""

    def test_success_result_factory(self):
        """Test creating a successful result"""
        result = ContainerStatusResult.success_result(
            docker_name='nginx',
            display_name='Web Server',
            is_running=True,
            cpu='5.2%',
            ram='128MB',
            uptime='2d 5h',
            details_allowed=True
        )

        assert result.success is True
        assert result.docker_name == 'nginx'
        assert result.display_name == 'Web Server'
        assert result.is_running is True
        assert result.cpu == '5.2%'
        assert result.ram == '128MB'
        assert result.uptime == '2d 5h'
        assert result.details_allowed is True
        assert result.error is None

    def test_error_result_factory(self):
        """Test creating an error result"""
        error = RuntimeError('Docker connection failed')
        result = ContainerStatusResult.error_result(
            docker_name='nginx',
            error=error,
            error_type='connectivity'
        )

        assert result.success is False
        assert result.docker_name == 'nginx'
        assert result.error == error
        assert result.error_message == 'Docker connection failed'
        assert result.error_type == 'connectivity'

    def test_offline_result_factory(self):
        """Test creating an offline result"""
        result = ContainerStatusResult.offline_result(
            docker_name='nginx',
            display_name='Web Server',
            details_allowed=True
        )

        assert result.success is True
        assert result.is_running is False
        assert result.is_offline is True
        assert result.is_online is False

    def test_is_online_property(self):
        """Test is_online property"""
        online = ContainerStatusResult.success_result(
            docker_name='nginx', display_name='nginx',
            is_running=True, cpu='5%', ram='100MB', uptime='1h',
            details_allowed=True
        )
        offline = ContainerStatusResult.offline_result(
            docker_name='nginx', display_name='nginx'
        )
        error = ContainerStatusResult.error_result(
            docker_name='nginx', error=Exception('fail')
        )

        assert online.is_online is True
        assert offline.is_online is False
        assert error.is_online is False

    def test_as_tuple_conversion(self):
        """Test backwards-compatible tuple conversion"""
        result = ContainerStatusResult.success_result(
            docker_name='nginx',
            display_name='Web Server',
            is_running=True,
            cpu='5.2%',
            ram='128MB',
            uptime='2d 5h',
            details_allowed=True
        )

        tuple_result = result.as_tuple()
        assert len(tuple_result) == 6
        assert tuple_result[0] == 'Web Server'
        assert tuple_result[1] is True
        assert tuple_result[2] == '5.2%'
        assert tuple_result[3] == '128MB'
        assert tuple_result[4] == '2d 5h'
        assert tuple_result[5] is True


class TestStatusHandlersRefactored:
    """Test suite for refactored StatusHandlersMixin"""

    @pytest.fixture
    def mixin(self):
        """Create a StatusHandlersMixin instance for testing"""
        bot = MockBot()
        mixin = StatusHandlersMixin()
        mixin.bot = bot
        mixin.pending_actions = {}  # Initialize pending actions dict
        mixin.cache_ttl_seconds = 30
        mixin.expanded_states = {}

        # Mock status_cache_service
        mock_cache_service = Mock()
        mock_cache_service.get = Mock(return_value=None)
        mock_cache_service.set = Mock()
        mock_cache_service.set_error = Mock()
        mixin.status_cache_service = mock_cache_service

        return mixin

    # =====================================================================
    # SECTION 1: ContainerStatusResult Integration Tests
    # =====================================================================

    @pytest.mark.asyncio
    async def test_get_status_returns_container_status_result(self, mixin):
        """Test that get_status returns ContainerStatusResult instead of tuple"""
        server_config = {
            'name': 'Test Server',
            'docker_name': 'test_container',
            'display_name': 'Test Server',
            'allow_detailed_status': True
        }

        mock_info = {
            'State': {
                'Status': 'running',
                'Running': True,
                'StartedAt': '2025-01-01T00:00:00Z'
            }
        }
        mock_stats = {
            'cpu_percent': 10.5,
            'memory_usage_mb': 256.0
        }

        with patch('cogs.status_handlers.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('cogs.status_handlers.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=mock_stats):

                result = await mixin.get_status(server_config)

                # Should return ContainerStatusResult, not tuple
                assert isinstance(result, ContainerStatusResult)
                assert result.success is True
                assert result.is_running is True
                assert result.docker_name == 'test_container'
                assert result.display_name == 'Test Server'

    @pytest.mark.asyncio
    async def test_get_status_error_returns_container_status_result(self, mixin):
        """Test that get_status returns ContainerStatusResult on error"""
        server_config = {
            'name': 'Test Server',
            'docker_name': 'test_container',
            'display_name': 'Test Server',
            'allow_detailed_status': True
        }

        with patch('cogs.status_handlers.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, side_effect=RuntimeError('Docker error')):

            result = await mixin.get_status(server_config)

            # Should return ContainerStatusResult with error
            assert isinstance(result, ContainerStatusResult)
            assert result.success is False
            assert isinstance(result.error, RuntimeError)
            assert result.error_message == 'Docker error'

    @pytest.mark.asyncio
    async def test_get_status_offline_returns_container_status_result(self, mixin):
        """Test that get_status returns ContainerStatusResult for offline container"""
        server_config = {
            'name': 'Test Server',
            'docker_name': 'test_container',
            'display_name': 'Test Server',
            'allow_detailed_status': True
        }

        # Return None to simulate container not found
        with patch('cogs.status_handlers.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=None):

            result = await mixin.get_status(server_config)

            # Should return offline result
            assert isinstance(result, ContainerStatusResult)
            assert result.success is True
            assert result.is_running is False
            assert result.is_offline is True

    # =====================================================================
    # SECTION 2: bulk_fetch_container_status Tests
    # =====================================================================

    @pytest.mark.asyncio
    async def test_bulk_fetch_returns_dict_of_container_status_results(self, mixin):
        """Test that bulk_fetch returns Dict[str, ContainerStatusResult]"""

        # Mock Docker connectivity (imported inside function, not at module level)
        with patch('services.infrastructure.docker_connectivity_service.get_docker_connectivity_service') as mock_conn:
            mock_conn_service = Mock()
            mock_result = Mock()
            mock_result.is_connected = True
            mock_conn_service.check_connectivity = AsyncMock(return_value=mock_result)
            mock_conn.return_value = mock_conn_service

            # Mock server config
            with patch('cogs.status_handlers.get_server_config_service') as mock_config:
                mock_config.return_value.get_all_servers.return_value = [
                    {'docker_name': 'container1', 'name': 'Server 1', 'allow_detailed_status': True},
                    {'docker_name': 'container2', 'name': 'Server 2', 'allow_detailed_status': True}
                ]

                # Mock fetch service
                with patch('cogs.status_handlers.get_fetch_service') as mock_fetch_svc:
                    mock_fetch_instance = Mock()

                    # Return mock fetch results with SERVICE FIRST format
                    async def mock_fetch(name):
                        return (name, {
                            'State': {'Running': True, 'StartedAt': '2025-01-01T00:00:00Z'},
                            '_computed': {
                                'cpu_percent': 10.0,
                                'memory_usage_mb': 128.0,
                                'uptime_seconds': 3600
                            }
                        }, None)

                    mock_fetch_instance.fetch_with_retries = AsyncMock(side_effect=mock_fetch)
                    mock_fetch_svc.return_value = mock_fetch_instance

                    # Mock performance service
                    with patch('cogs.status_handlers.get_performance_service') as mock_perf:
                        mock_perf_instance = Mock()
                        mock_classification = Mock()
                        mock_classification.fast_containers = ['container1', 'container2']
                        mock_classification.slow_containers = []
                        mock_perf_instance.classify_containers = Mock(return_value=mock_classification)
                        mock_perf.return_value = mock_perf_instance

                        results = await mixin.bulk_fetch_container_status(['container1', 'container2'])

                        # Should return Dict[str, ContainerStatusResult]
                        assert isinstance(results, dict)
                        assert 'container1' in results
                        assert 'container2' in results
                        assert isinstance(results['container1'], ContainerStatusResult)
                        assert isinstance(results['container2'], ContainerStatusResult)
                        assert results['container1'].success is True
                        assert results['container2'].success is True

    @pytest.mark.asyncio
    async def test_bulk_fetch_docker_connectivity_failure(self, mixin):
        """Test bulk_fetch handles Docker connectivity failure"""

        # Mock Docker connectivity failure (imported inside function, not at module level)
        with patch('services.infrastructure.docker_connectivity_service.get_docker_connectivity_service') as mock_conn:
            mock_conn_service = Mock()
            mock_result = Mock()
            mock_result.is_connected = False
            mock_result.error_message = 'Docker daemon not running'
            mock_conn_service.check_connectivity = AsyncMock(return_value=mock_result)
            mock_conn.return_value = mock_conn_service

            results = await mixin.bulk_fetch_container_status(['container1', 'container2'])

            # Should return error results for all containers
            assert isinstance(results, dict)
            assert len(results) == 2
            assert all(isinstance(r, ContainerStatusResult) for r in results.values())
            assert all(r.success is False for r in results.values())
            assert all(r.error_type == 'connectivity' for r in results.values())

    @pytest.mark.asyncio
    async def test_bulk_fetch_empty_list(self, mixin):
        """Test bulk_fetch with empty container list"""
        results = await mixin.bulk_fetch_container_status([])

        assert isinstance(results, dict)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_bulk_fetch_performance_classification(self, mixin):
        """Test that bulk_fetch uses performance classification for intelligent batching"""

        # Mock Docker connectivity (imported inside function, not at module level)
        with patch('services.infrastructure.docker_connectivity_service.get_docker_connectivity_service') as mock_conn:
            mock_conn_service = Mock()
            mock_result = Mock()
            mock_result.is_connected = True
            mock_conn_service.check_connectivity = AsyncMock(return_value=mock_result)
            mock_conn.return_value = mock_conn_service

            # Mock performance service with classification
            with patch('cogs.status_handlers.get_performance_service') as mock_perf:
                mock_perf_instance = Mock()
                mock_classification = Mock()
                mock_classification.fast_containers = ['fast1', 'fast2']
                mock_classification.slow_containers = ['slow1']
                mock_perf_instance.classify_containers = Mock(return_value=mock_classification)
                mock_perf.return_value = mock_perf_instance

                # Mock server config
                with patch('cogs.status_handlers.get_server_config_service') as mock_config:
                    mock_config.return_value.get_all_servers.return_value = [
                        {'docker_name': 'fast1', 'name': 'Fast 1', 'allow_detailed_status': True},
                        {'docker_name': 'fast2', 'name': 'Fast 2', 'allow_detailed_status': True},
                        {'docker_name': 'slow1', 'name': 'Slow 1', 'allow_detailed_status': True}
                    ]

                    # Mock fetch service
                    with patch('cogs.status_handlers.get_fetch_service') as mock_fetch_svc:
                        mock_fetch_instance = Mock()

                        async def mock_fetch(name):
                            return (name, {
                                'State': {'Running': True, 'StartedAt': '2025-01-01T00:00:00Z'},
                                '_computed': {
                                    'cpu_percent': 10.0,
                                    'memory_usage_mb': 128.0,
                                    'uptime_seconds': 3600
                                }
                            }, None)

                        mock_fetch_instance.fetch_with_retries = AsyncMock(side_effect=mock_fetch)
                        mock_fetch_svc.return_value = mock_fetch_instance

                        results = await mixin.bulk_fetch_container_status(['fast1', 'fast2', 'slow1'])

                        # Verify classify_containers was called
                        mock_perf_instance.classify_containers.assert_called_once_with(['fast1', 'fast2', 'slow1'])

                        # All containers should have results
                        assert len(results) == 3

    # =====================================================================
    # SECTION 3: Pending Status Tests
    # =====================================================================

    @pytest.mark.asyncio
    async def test_generate_embed_pending_status_start(self, mixin):
        """Test that pending status is shown for start action"""
        display_name = 'Test Server'
        server_conf = {
            'name': display_name,
            'docker_name': 'test_container',
            'allow_detailed_status': True
        }
        current_config = {'language': 'de', 'timezone_str': 'Europe/Berlin'}

        # Set pending action (start)
        now = datetime.now(timezone.utc)
        mixin.pending_actions['test_container'] = {
            'action': 'start',
            'timestamp': now
        }

        # Mock server config service
        with patch('cogs.status_handlers.get_server_config_service') as mock_config:
            mock_config.return_value.get_all_servers.return_value = [server_conf]

            embed, view, running = await mixin._generate_status_embed_and_view(
                channel_id=123456,
                display_name=display_name,
                server_conf=server_conf,
                current_config=current_config
            )

            # Should return pending embed
            assert embed is not None
            assert view is None  # No view during pending
            assert running is False  # Running status should be False during pending

    @pytest.mark.asyncio
    async def test_pending_status_timeout_with_action_success(self, mixin):
        """Test pending timeout when action succeeds"""
        display_name = 'Test Server'
        docker_name = 'test_container'
        server_conf = {
            'name': display_name,
            'docker_name': docker_name,
            'allow_detailed_status': True
        }
        current_config = {'language': 'de', 'timezone_str': 'Europe/Berlin'}

        # Set pending action that timed out (121 seconds ago)
        timeout_time = datetime.now(timezone.utc) - timedelta(seconds=121)
        mixin.pending_actions[docker_name] = {
            'action': 'start',
            'timestamp': timeout_time
        }

        # Mock get_status to return running container (start succeeded)
        mock_result = ContainerStatusResult.success_result(
            docker_name=docker_name,
            display_name=display_name,
            is_running=True,
            cpu='10%',
            ram='100MB',
            uptime='1m',
            details_allowed=True
        )

        # Mock server config service
        with patch('cogs.status_handlers.get_server_config_service') as mock_config:
            mock_config.return_value.get_all_servers.return_value = [server_conf]

            with patch.object(mixin, 'get_status', new_callable=AsyncMock, return_value=mock_result):

                embed, view, running = await mixin._generate_status_embed_and_view(
                    channel_id=123456,
                    display_name=display_name,
                    server_conf=server_conf,
                    current_config=current_config
                )

                # Pending action should be cleared (start succeeded)
                assert docker_name not in mixin.pending_actions

                # Cache should be updated
                mixin.status_cache_service.set.assert_called()

    @pytest.mark.asyncio
    async def test_pending_status_timeout_with_action_failure(self, mixin):
        """Test pending timeout when action fails"""
        display_name = 'Test Server'
        docker_name = 'test_container'
        server_conf = {
            'name': display_name,
            'docker_name': docker_name,
            'allow_detailed_status': True
        }
        current_config = {'language': 'de', 'timezone_str': 'Europe/Berlin'}

        # Set pending action for 'start' that timed out
        timeout_time = datetime.now(timezone.utc) - timedelta(seconds=121)
        mixin.pending_actions[docker_name] = {
            'action': 'start',
            'timestamp': timeout_time
        }

        # Mock get_status to return stopped container (start failed)
        mock_result = ContainerStatusResult.offline_result(
            docker_name=docker_name,
            display_name=display_name,
            details_allowed=True
        )

        # Mock server config service
        with patch('cogs.status_handlers.get_server_config_service') as mock_config:
            mock_config.return_value.get_all_servers.return_value = [server_conf]

            with patch.object(mixin, 'get_status', new_callable=AsyncMock, return_value=mock_result):

                await mixin._generate_status_embed_and_view(
                    channel_id=123456,
                    display_name=display_name,
                    server_conf=server_conf,
                    current_config=current_config
                )

                # Pending action should still be cleared (timeout reached)
                assert docker_name not in mixin.pending_actions

    # =====================================================================
    # SECTION 4: Cache Integration Tests
    # =====================================================================

    @pytest.mark.asyncio
    async def test_bulk_update_cache_with_container_status_result(self, mixin):
        """Test that bulk_update_status_cache handles ContainerStatusResult"""

        # Mock server config
        with patch('cogs.status_handlers.get_server_config_service') as mock_config:
            mock_config.return_value.get_all_servers.return_value = [
                {'docker_name': 'container1', 'name': 'Server 1'},
                {'docker_name': 'container2', 'name': 'Server 2'}
            ]

            # Mock bulk_fetch to return ContainerStatusResult
            mock_results = {
                'container1': ContainerStatusResult.success_result(
                    docker_name='container1',
                    display_name='Server 1',
                    is_running=True,
                    cpu='5%',
                    ram='100MB',
                    uptime='1h',
                    details_allowed=True
                ),
                'container2': ContainerStatusResult.error_result(
                    docker_name='container2',
                    error=RuntimeError('Failed'),
                    error_type='timeout'
                )
            }

            with patch.object(mixin, 'bulk_fetch_container_status',
                              new_callable=AsyncMock,
                              return_value=mock_results):

                await mixin.bulk_update_status_cache(['container1', 'container2'])

                # Successful result should call set()
                success_call = [call for call in mixin.status_cache_service.set.call_args_list
                               if call[0][0] == 'Server 1']
                assert len(success_call) == 1

                # Error result should call set_error()
                mixin.status_cache_service.set_error.assert_called_once()


# =========================================================================
# Test Configuration
# =========================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
