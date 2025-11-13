#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for StatusHandlersMixin - Current Implementation

Tests cover the 5 main responsibilities during refactoring:
1. Performance Learning System (via PerformanceProfileService)
2. Docker Status Fetching (Retry Logic)
3. Cache Management
4. Embed Building
5. Container Classification

These tests ensure no functionality is lost during the Service extraction refactoring.
"""
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from typing import Dict, Any

# Import the class we're testing
from cogs.status_handlers import StatusHandlersMixin
from services.docker_status import get_performance_service, get_fetch_service
from services.discord import get_conditional_cache_service


class MockBot:
    """Mock Discord bot for testing"""
    def __init__(self):
        self.user = Mock()
        self.user.id = 123456789


class TestStatusHandlersMixin:
    """Test suite for StatusHandlersMixin"""

    @pytest.fixture
    def mixin(self):
        """Create a StatusHandlersMixin instance for testing"""
        bot = MockBot()
        mixin = StatusHandlersMixin()
        mixin.bot = bot
        return mixin

    @pytest.fixture
    def perf_service(self):
        """Get the PerformanceProfileService for testing"""
        service = get_performance_service()
        # Clear any existing profiles for clean test state
        service._profiles.clear()
        return service

    @pytest.fixture
    def cache_service(self):
        """Get the ConditionalUpdateCacheService for testing"""
        service = get_conditional_cache_service()
        # Clear cache and reset stats for clean test state
        service.clear_cache()
        service.reset_statistics()
        return service

    @pytest.fixture
    def fetch_service(self):
        """Get the DockerStatusFetchService for testing"""
        service = get_fetch_service()
        # Clear query history for clean test state
        service.clear_query_history()
        return service


    # =====================================================================
    # SECTION 1: Performance Learning System Tests
    # =====================================================================

    def test_performance_service_initialization(self, perf_service):
        """Test that performance service is properly initialized"""
        config = perf_service.get_config()

        # Check config values exist and are correct types
        assert config.retry_attempts > 0
        assert config.default_timeout > 0
        assert config.slow_threshold > 0
        assert config.min_timeout > 0
        assert config.max_timeout > config.min_timeout
        assert config.history_window > 0
        assert config.timeout_multiplier > 0


    def test_get_container_performance_profile_new_container(self, perf_service):
        """Test getting profile for a container that doesn't have history"""
        profile = perf_service.get_profile('test_container')

        assert profile.container_name == 'test_container'
        assert isinstance(profile.response_times, list)
        assert len(profile.response_times) == 0
        assert profile.avg_response_time == perf_service.get_config().default_timeout
        assert profile.success_rate == 1.0
        assert profile.is_slow is False
        assert profile.total_attempts == 0
        assert profile.successful_attempts == 0


    def test_get_container_performance_profile_existing_container(self, perf_service):
        """Test getting profile for a container with existing history"""
        # Create existing profile by updating performance
        perf_service.update_performance('existing_container', 100, True)
        perf_service.update_performance('existing_container', 200, True)
        perf_service.update_performance('existing_container', 150, True)
        perf_service.update_performance('existing_container', 0, False)  # One failure
        perf_service.update_performance('existing_container', 0, False)  # Another failure

        profile = perf_service.get_profile('existing_container')

        assert profile.avg_response_time == 150  # (100 + 200 + 150) / 3
        assert profile.success_rate == 0.6  # 3 success / 5 total
        assert len(profile.response_times) == 3


    def test_update_container_performance_success(self, perf_service):
        """Test updating performance history with successful fetch"""
        # Update with successful fetch
        perf_service.update_performance('test_container', 100.0, True)

        profile = perf_service.get_profile('test_container')
        assert len(profile.response_times) == 1
        assert profile.response_times[0] == 100.0
        assert profile.avg_response_time == 100.0
        assert profile.success_rate == 1.0
        assert profile.total_attempts == 1
        assert profile.successful_attempts == 1


    def test_update_container_performance_failure(self, perf_service):
        """Test updating performance history with failed fetch"""
        # First successful fetch
        perf_service.update_performance('test_container', 100.0, True)
        # Then failed fetch
        perf_service.update_performance('test_container', 0, False)

        profile = perf_service.get_profile('test_container')
        # Failed fetch should not add to response_times
        assert len(profile.response_times) == 1
        # But should affect success rate
        assert profile.success_rate < 1.0
        assert profile.total_attempts == 2
        assert profile.successful_attempts == 1


    def test_update_container_performance_history_limit(self, perf_service):
        """Test that performance history is limited to history_window"""
        history_window = perf_service.get_config().history_window

        # Add more entries than history_window
        for i in range(history_window + 10):
            perf_service.update_performance('test_container', float(i * 10), True)

        profile = perf_service.get_profile('test_container')
        # History should not exceed history_window
        assert len(profile.response_times) <= history_window


    def test_get_adaptive_timeout_fast_container(self, perf_service):
        """Test adaptive timeout calculation for fast containers"""
        # Add measurements to build fast container profile (100ms average)
        for time_val in [80, 90, 100, 110, 120]:
            perf_service.update_performance('fast_container', time_val, True)

        timeout = perf_service.get_adaptive_timeout('fast_container')

        # Timeout should be reasonable for fast container
        assert timeout > 100  # Should be higher than avg
        assert timeout <= perf_service.get_config().max_timeout  # Should not exceed max


    def test_get_adaptive_timeout_slow_container(self, perf_service):
        """Test adaptive timeout calculation for slow containers"""
        # Add measurements to build slow container profile (3000ms average with some failures)
        for time_val in [2800, 2900, 3000, 3100, 3200]:
            perf_service.update_performance('slow_container', time_val, True)
        # Add two failures to reduce success rate to 0.8 (8/10)
        perf_service.update_performance('slow_container', 0, False)
        perf_service.update_performance('slow_container', 0, False)

        timeout = perf_service.get_adaptive_timeout('slow_container')

        # Timeout should be higher for slow container
        assert timeout > 3000


    def test_get_adaptive_timeout_new_container(self, perf_service):
        """Test adaptive timeout for container without history"""
        timeout = perf_service.get_adaptive_timeout('new_container')

        # Should return default timeout from config (new containers use default_timeout)
        default_timeout = perf_service.get_config().default_timeout
        # Timeout should be based on default_timeout with multiplier
        assert timeout >= default_timeout


    def test_classify_containers_by_performance(self, perf_service):
        """Test container classification into fast/slow categories"""
        # Build fast container profiles
        for time_val in [100, 120, 110]:
            perf_service.update_performance('fast1', time_val, True)

        for time_val in [90, 95, 100]:
            perf_service.update_performance('fast2', time_val, True)

        # Build slow container profile
        for time_val in [3000, 3100, 2900]:
            perf_service.update_performance('slow1', time_val, True)
        # Add failures to reduce success rate to 0.7 (7/10)
        for _ in range(3):
            perf_service.update_performance('slow1', 0, False)

        container_names = ['fast1', 'fast2', 'slow1', 'new_container']
        classification = perf_service.classify_containers(container_names)

        # Fast containers should be identified
        assert 'fast1' in classification.fast_containers
        assert 'fast2' in classification.fast_containers

        # Slow containers should be identified
        assert 'slow1' in classification.slow_containers

        # New container should be in unknown (no history yet)
        assert 'new_container' in classification.unknown_containers


    # =====================================================================
    # SECTION 2: Docker Status Fetching Tests (Async)
    # =====================================================================

    @pytest.mark.asyncio
    async def test_fetch_container_with_retries_success_first_attempt(self, fetch_service):
        """Test successful fetch on first attempt"""

        # Mock the docker fetch functions
        mock_info = {'State': {'Status': 'running'}}
        mock_stats = {'cpu_stats': {}}

        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=mock_stats):

                container_name, info, stats = await fetch_service.fetch_with_retries('test_container')

                assert container_name == 'test_container'
                assert info == mock_info
                assert stats == mock_stats


    @pytest.mark.asyncio
    async def test_fetch_container_with_retries_timeout_then_success(self, fetch_service):
        """Test retry logic when first attempt times out"""

        mock_info = {'State': {'Status': 'running'}}
        mock_stats = {'cpu_stats': {}}

        # First call raises timeout, second succeeds
        info_mock = AsyncMock()
        info_mock.side_effect = [asyncio.TimeoutError(), mock_info]

        stats_mock = AsyncMock()
        stats_mock.side_effect = [asyncio.TimeoutError(), mock_stats]

        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first', info_mock):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first', stats_mock):

                container_name, info, stats = await fetch_service.fetch_with_retries('test_container')

                # Should eventually succeed
                assert container_name == 'test_container'


    @pytest.mark.asyncio
    async def test_fetch_container_with_retries_all_fail(self, fetch_service):
        """Test behavior when all retries fail"""

        # Mock that always times out
        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):
                with patch.object(fetch_service, '_emergency_full_fetch',
                                  new_callable=AsyncMock,
                                  return_value=('test_container', Exception('All failed'), None)):

                    container_name, info, stats = await fetch_service.fetch_with_retries('test_container')

                    # Should call emergency fetch after all retries fail
                    assert container_name == 'test_container'
                    assert isinstance(info, Exception)


    # =====================================================================
    # SECTION 3: Cache Management Tests
    # =====================================================================

    def test_conditional_cache_service_initialization(self, cache_service):
        """Test that conditional cache service is properly initialized"""
        stats = cache_service.get_statistics()

        assert stats['skipped'] == 0
        assert stats['sent'] == 0
        assert stats['total'] == 0
        assert stats['cache_size'] == 0


    @pytest.mark.asyncio
    async def test_bulk_update_status_cache(self, mixin):
        """Test bulk cache update operation"""

        # Mock status_cache_service
        mock_cache_service = Mock()
        mock_cache_service.get = Mock(return_value=None)  # No existing cache
        mock_cache_service.set = Mock()
        mock_cache_service.set_error = Mock()
        mixin.status_cache_service = mock_cache_service

        # Mock bulk fetch - returns (status, data, error) tuples
        mock_data1 = ('Test Server 1', True, '10%', '100MB', '1h', True)
        mock_data2 = ('Test Server 2', False, 'N/A', 'N/A', 'N/A', True)
        mock_results = {
            'container1': ('success', mock_data1, None),
            'container2': ('success', mock_data2, None)
        }

        # Mock server config service
        with patch('cogs.status_handlers.get_server_config_service') as mock_config:
            mock_config.return_value.get_all_servers.return_value = [
                {'docker_name': 'container1', 'name': 'Test Server 1'},
                {'docker_name': 'container2', 'name': 'Test Server 2'}
            ]

            with patch.object(mixin, 'bulk_fetch_container_status',
                              new_callable=AsyncMock,
                              return_value=mock_results):

                await mixin.bulk_update_status_cache(['container1', 'container2'])

                # Cache set should be called for both containers
                assert mock_cache_service.set.call_count == 2


    # =====================================================================
    # SECTION 4: Embed Building Tests
    # =====================================================================

    def test_get_cached_translations(self, mixin):
        """Test translation caching"""
        translations_de = mixin._get_cached_translations('de')
        translations_en = mixin._get_cached_translations('en')

        assert isinstance(translations_de, dict)
        assert isinstance(translations_en, dict)

        # Should have required keys (actual keys from implementation)
        assert 'online_text' in translations_de or 'offline_text' in translations_de
        assert 'cpu_text' in translations_de
        assert 'ram_text' in translations_de

        # Calling again should return cached version (same object)
        translations_de_2 = mixin._get_cached_translations('de')
        assert translations_de is translations_de_2


    def test_get_cached_box_elements(self, mixin):
        """Test box elements caching for status display"""
        box_elements = mixin._get_cached_box_elements('test_container', BOX_WIDTH=28)

        assert isinstance(box_elements, dict)
        # Should have common box drawing elements (actual keys from implementation)
        assert 'header_line' in box_elements
        assert 'footer_line' in box_elements


    # =====================================================================
    # SECTION 5: Integration Tests (Status Operations)
    # =====================================================================

    @pytest.mark.asyncio
    async def test_get_status_online_container(self, mixin):
        """Test get_status for an online container"""

        server_config = {
            'name': 'Test Server',
            'docker_name': 'test_container',
            'display_name': 'Test Server',
            'allow_detailed_status': True
        }

        # Mock docker responses
        mock_info = {
            'State': {
                'Status': 'running',
                'Running': True,
                'StartedAt': '2025-01-01T00:00:00Z'
            },
            'Name': '/test_container'
        }
        # Mock stats in the new format with computed values
        mock_stats = {
            'cpu_percent': 10.5,
            'memory_usage_mb': 256.0
        }

        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=mock_stats):

                result = await mixin.get_status(server_config)

                # Should return tuple with status info (display_name, is_running, cpu, ram, uptime, details_allowed)
                assert isinstance(result, tuple)
                assert len(result) == 6
                # First element should be display_name
                assert result[0] == 'Test Server'
                # Second element should be is_running
                assert result[1] is True


    @pytest.mark.asyncio
    async def test_get_status_offline_container(self, mixin):
        """Test get_status for an offline container"""

        server_config = {
            'name': 'Test Server',
            'docker_name': 'test_container',
            'display_name': 'Test Server',
            'allow_detailed_status': True
        }

        # Mock docker responses for stopped container
        mock_info = {
            'State': {
                'Status': 'exited',
                'Running': False,
                'FinishedAt': '2025-01-01T00:00:00Z'
            },
            'Name': '/test_container'
        }

        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=None):

                result = await mixin.get_status(server_config)

                # Should return tuple with offline status (display_name, is_running, cpu, ram, uptime, details_allowed)
                assert isinstance(result, tuple)
                assert len(result) == 6
                assert result[0] == 'Test Server'
                assert result[1] is False  # Container is not running


    @pytest.mark.asyncio
    async def test_get_status_error_handling(self, mixin):
        """Test get_status error handling when docker fails"""

        server_config = {
            'name': 'Test Server',
            'docker_name': 'test_container',
            'display_name': 'Test Server',
            'allow_detailed_status': True
        }

        # Mock docker fetch failure
        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, side_effect=RuntimeError('Docker error')):

            result = await mixin.get_status(server_config)

            # Should return Exception
            assert isinstance(result, Exception)


# =========================================================================
# Test Configuration
# =========================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
