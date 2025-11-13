#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for StatusHandlersMixin - Current Implementation

Tests cover the 5 main responsibilities before refactoring:
1. Performance Learning System
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


    # =====================================================================
    # SECTION 1: Performance Learning System Tests
    # =====================================================================

    def test_ensure_performance_system_initialization(self, mixin):
        """Test that performance system is properly initialized"""
        mixin._ensure_performance_system()

        assert hasattr(mixin, 'container_performance_history')
        assert hasattr(mixin, 'performance_learning_config')
        assert isinstance(mixin.container_performance_history, dict)
        assert isinstance(mixin.performance_learning_config, dict)

        # Check default config values
        config = mixin.performance_learning_config
        assert 'retry_attempts' in config
        assert 'default_timeout' in config
        assert 'slow_threshold' in config


    def test_get_container_performance_profile_new_container(self, mixin):
        """Test getting profile for a container that doesn't have history"""
        mixin._ensure_performance_system()

        profile = mixin._get_container_performance_profile('test_container')

        assert isinstance(profile, dict)
        assert 'response_times' in profile
        assert 'avg_response_time' in profile
        assert 'max_response_time' in profile
        assert 'min_response_time' in profile
        assert 'success_rate' in profile
        assert 'total_attempts' in profile
        assert 'successful_attempts' in profile
        assert 'is_slow' in profile
        assert 'last_updated' in profile
        assert profile['avg_response_time'] == mixin.performance_learning_config['default_timeout']
        assert profile['success_rate'] == 1.0
        assert profile['is_slow'] is False


    def test_get_container_performance_profile_existing_container(self, mixin):
        """Test getting profile for a container with existing history"""
        mixin._ensure_performance_system()

        # Create existing profile with correct structure
        mixin.container_performance_history['existing_container'] = {
            'response_times': [100, 200, 150],
            'avg_response_time': 150,
            'max_response_time': 200,
            'min_response_time': 100,
            'success_rate': 0.8,
            'total_attempts': 5,
            'successful_attempts': 4,
            'is_slow': False,
            'last_updated': None
        }

        profile = mixin._get_container_performance_profile('existing_container')

        assert profile['avg_response_time'] == 150
        assert profile['success_rate'] == 0.8
        assert len(profile['response_times']) == 3


    def test_update_container_performance_success(self, mixin):
        """Test updating performance history with successful fetch"""
        mixin._ensure_performance_system()

        # Update with successful fetch
        mixin._update_container_performance('test_container', 100.0, True)

        profile = mixin.container_performance_history['test_container']
        assert len(profile['response_times']) == 1
        assert profile['response_times'][0] == 100.0
        assert profile['avg_response_time'] == 100.0
        assert profile['success_rate'] == 1.0
        assert profile['total_attempts'] == 1
        assert profile['successful_attempts'] == 1


    def test_update_container_performance_failure(self, mixin):
        """Test updating performance history with failed fetch"""
        mixin._ensure_performance_system()

        # First successful fetch
        mixin._update_container_performance('test_container', 100.0, True)
        # Then failed fetch
        mixin._update_container_performance('test_container', 0, False)

        profile = mixin.container_performance_history['test_container']
        # Failed fetch should not add to response_times
        assert len(profile['response_times']) == 1
        # But should affect success rate
        assert profile['success_rate'] < 1.0
        assert profile['total_attempts'] == 2
        assert profile['successful_attempts'] == 1


    def test_update_container_performance_history_limit(self, mixin):
        """Test that performance history is limited to history_window"""
        mixin._ensure_performance_system()
        history_window = mixin.performance_learning_config['history_window']

        # Add more entries than history_window
        for i in range(history_window + 10):
            mixin._update_container_performance('test_container', float(i * 10), True)

        profile = mixin.container_performance_history['test_container']
        # History should not exceed history_window
        assert len(profile['response_times']) <= history_window


    def test_get_adaptive_timeout_fast_container(self, mixin):
        """Test adaptive timeout calculation for fast containers"""
        mixin._ensure_performance_system()

        # Simulate fast container (100ms average)
        mixin.container_performance_history['fast_container'] = {
            'response_times': [80, 90, 100, 110, 120],
            'avg_response_time': 100,
            'max_response_time': 120,
            'min_response_time': 80,
            'success_rate': 1.0,
            'total_attempts': 5,
            'successful_attempts': 5,
            'is_slow': False,
            'last_updated': None
        }

        timeout = mixin._get_adaptive_timeout('fast_container')

        # Timeout should be reasonable for fast container
        assert timeout > 100  # Should be higher than avg
        assert timeout <= mixin.performance_learning_config['max_timeout']  # Should not exceed max


    def test_get_adaptive_timeout_slow_container(self, mixin):
        """Test adaptive timeout calculation for slow containers"""
        mixin._ensure_performance_system()

        # Simulate slow container (3000ms average)
        mixin.container_performance_history['slow_container'] = {
            'response_times': [2800, 2900, 3000, 3100, 3200],
            'avg_response_time': 3000,
            'max_response_time': 3200,
            'min_response_time': 2800,
            'success_rate': 0.8,
            'total_attempts': 10,
            'successful_attempts': 8,
            'is_slow': True,
            'last_updated': None
        }

        timeout = mixin._get_adaptive_timeout('slow_container')

        # Timeout should be higher for slow container
        assert timeout > 3000


    def test_get_adaptive_timeout_new_container(self, mixin):
        """Test adaptive timeout for container without history"""
        mixin._ensure_performance_system()

        timeout = mixin._get_adaptive_timeout('new_container')

        # Should return default timeout from config (new containers use default_timeout)
        default_timeout = mixin.performance_learning_config['default_timeout']
        # Timeout should be based on default_timeout with multiplier
        assert timeout >= default_timeout


    def test_classify_containers_by_performance(self, mixin):
        """Test container classification into fast/slow categories"""
        mixin._ensure_performance_system()

        # Create mix of fast and slow containers
        mixin.container_performance_history['fast1'] = {
            'response_times': [100, 120, 110],
            'avg_response_time': 110,
            'max_response_time': 120,
            'min_response_time': 100,
            'success_rate': 1.0,
            'total_attempts': 3,
            'successful_attempts': 3,
            'is_slow': False,
            'last_updated': None
        }
        mixin.container_performance_history['fast2'] = {
            'response_times': [90, 95, 100],
            'avg_response_time': 95,
            'max_response_time': 100,
            'min_response_time': 90,
            'success_rate': 1.0,
            'total_attempts': 3,
            'successful_attempts': 3,
            'is_slow': False,
            'last_updated': None
        }
        mixin.container_performance_history['slow1'] = {
            'response_times': [3000, 3100, 2900],
            'avg_response_time': 3000,
            'max_response_time': 3100,
            'min_response_time': 2900,
            'success_rate': 0.7,
            'total_attempts': 10,
            'successful_attempts': 7,
            'is_slow': True,
            'last_updated': None
        }

        container_names = ['fast1', 'fast2', 'slow1', 'new_container']
        fast, slow = mixin._classify_containers_by_performance(container_names)

        # Fast containers should be identified
        assert 'fast1' in fast
        assert 'fast2' in fast

        # Slow containers should be identified
        assert 'slow1' in slow

        # New container should default to fast
        assert 'new_container' in fast


    # =====================================================================
    # SECTION 2: Docker Status Fetching Tests (Async)
    # =====================================================================

    @pytest.mark.asyncio
    async def test_fetch_container_with_retries_success_first_attempt(self, mixin):
        """Test successful fetch on first attempt"""
        mixin._ensure_performance_system()

        # Mock the docker fetch functions
        mock_info = {'State': {'Status': 'running'}}
        mock_stats = {'cpu_stats': {}}

        with patch('cogs.status_handlers.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('cogs.status_handlers.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=mock_stats):

                container_name, info, stats = await mixin._fetch_container_with_retries('test_container')

                assert container_name == 'test_container'
                assert info == mock_info
                assert stats == mock_stats


    @pytest.mark.asyncio
    async def test_fetch_container_with_retries_timeout_then_success(self, mixin):
        """Test retry logic when first attempt times out"""
        mixin._ensure_performance_system()

        mock_info = {'State': {'Status': 'running'}}
        mock_stats = {'cpu_stats': {}}

        # First call raises timeout, second succeeds
        info_mock = AsyncMock()
        info_mock.side_effect = [asyncio.TimeoutError(), mock_info]

        stats_mock = AsyncMock()
        stats_mock.side_effect = [asyncio.TimeoutError(), mock_stats]

        with patch('cogs.status_handlers.get_docker_info_dict_service_first', info_mock):
            with patch('cogs.status_handlers.get_docker_stats_service_first', stats_mock):

                container_name, info, stats = await mixin._fetch_container_with_retries('test_container')

                # Should eventually succeed
                assert container_name == 'test_container'


    @pytest.mark.asyncio
    async def test_fetch_container_with_retries_all_fail(self, mixin):
        """Test behavior when all retries fail"""
        mixin._ensure_performance_system()

        # Mock that always times out
        with patch('cogs.status_handlers.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):
            with patch('cogs.status_handlers.get_docker_stats_service_first',
                       new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):
                with patch.object(mixin, '_emergency_full_fetch',
                                  new_callable=AsyncMock,
                                  return_value=('test_container', Exception('All failed'), None)):

                    container_name, info, stats = await mixin._fetch_container_with_retries('test_container')

                    # Should call emergency fetch after all retries fail
                    assert container_name == 'test_container'
                    assert isinstance(info, Exception)


    # =====================================================================
    # SECTION 3: Cache Management Tests
    # =====================================================================

    def test_ensure_conditional_cache_initialization(self, mixin):
        """Test that conditional cache is properly initialized"""
        mixin._ensure_conditional_cache()

        assert hasattr(mixin, 'last_sent_content')
        assert isinstance(mixin.last_sent_content, dict)
        assert hasattr(mixin, 'update_stats')
        assert isinstance(mixin.update_stats, dict)


    @pytest.mark.asyncio
    async def test_bulk_update_status_cache(self, mixin):
        """Test bulk cache update operation"""
        mixin._ensure_conditional_cache()
        mixin._ensure_performance_system()

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
        mixin._ensure_conditional_cache()
        mixin._ensure_performance_system()

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

        with patch('cogs.status_handlers.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('cogs.status_handlers.get_docker_stats_service_first',
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
        mixin._ensure_conditional_cache()
        mixin._ensure_performance_system()

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

        with patch('cogs.status_handlers.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('cogs.status_handlers.get_docker_stats_service_first',
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
        mixin._ensure_conditional_cache()
        mixin._ensure_performance_system()

        server_config = {
            'name': 'Test Server',
            'docker_name': 'test_container',
            'display_name': 'Test Server',
            'allow_detailed_status': True
        }

        # Mock docker fetch failure
        with patch('cogs.status_handlers.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, side_effect=RuntimeError('Docker error')):

            result = await mixin.get_status(server_config)

            # Should return Exception
            assert isinstance(result, Exception)


# =========================================================================
# Test Configuration
# =========================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
