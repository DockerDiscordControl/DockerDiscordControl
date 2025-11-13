#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for Docker Status Services

Tests for the service layer extracted from StatusHandlersMixin:
1. PerformanceProfileService - Performance tracking and adaptive timeouts
2. DockerStatusFetchService - Docker data fetching with retry logic
3. ConditionalUpdateCacheService - Smart content-based caching

These tests ensure the service layer works correctly in isolation.
"""
import sys
from unittest.mock import Mock, MagicMock

# Mock docker module before any imports that depend on it
sys.modules['docker'] = MagicMock()
sys.modules['docker.errors'] = MagicMock()

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

# Import services to test
from services.docker_status import (
    get_performance_service,
    get_fetch_service,
    PerformanceProfile,
    StatusFetchRequest,
    StatusFetchResult
)
from services.discord import get_conditional_cache_service


class TestPerformanceProfileService:
    """Test suite for PerformanceProfileService"""

    @pytest.fixture
    def perf_service(self):
        """Get clean PerformanceProfileService instance"""
        service = get_performance_service()
        service._profiles.clear()
        return service

    # =====================================================================
    # Profile Management Tests
    # =====================================================================

    def test_get_profile_new_container(self, perf_service):
        """Test getting profile for container without history"""
        profile = perf_service.get_profile('new_container')

        assert isinstance(profile, PerformanceProfile)
        assert profile.container_name == 'new_container'
        assert len(profile.response_times) == 0
        assert profile.avg_response_time == perf_service.get_config().default_timeout
        assert profile.success_rate == 1.0
        assert profile.total_attempts == 0
        assert profile.is_slow is False

    def test_get_profile_existing_container(self, perf_service):
        """Test getting profile for container with history"""
        # Add some performance data
        perf_service.update_performance('existing', 100, True)
        perf_service.update_performance('existing', 200, True)
        perf_service.update_performance('existing', 150, True)

        profile = perf_service.get_profile('existing')

        assert profile.avg_response_time == 150.0
        assert len(profile.response_times) == 3
        assert profile.total_attempts == 3
        assert profile.successful_attempts == 3
        assert profile.success_rate == 1.0

    # =====================================================================
    # Performance Update Tests
    # =====================================================================

    def test_update_performance_success(self, perf_service):
        """Test updating performance with successful fetch"""
        perf_service.update_performance('test', 250.5, True)

        profile = perf_service.get_profile('test')
        assert len(profile.response_times) == 1
        assert profile.response_times[0] == 250.5
        assert profile.total_attempts == 1
        assert profile.successful_attempts == 1
        assert profile.success_rate == 1.0

    def test_update_performance_failure(self, perf_service):
        """Test updating performance with failed fetch"""
        perf_service.update_performance('test', 100, True)
        perf_service.update_performance('test', 0, False)

        profile = perf_service.get_profile('test')
        assert len(profile.response_times) == 1  # Failures don't add to times
        assert profile.total_attempts == 2
        assert profile.successful_attempts == 1
        assert profile.success_rate == 0.5

    def test_update_performance_history_limit(self, perf_service):
        """Test that performance history respects window limit"""
        window = perf_service.get_config().history_window

        # Add more entries than window allows
        for i in range(window + 10):
            perf_service.update_performance('test', float(i * 10), True)

        profile = perf_service.get_profile('test')
        assert len(profile.response_times) <= window

    def test_update_performance_calculates_stats(self, perf_service):
        """Test that update correctly calculates avg/min/max"""
        times = [100, 200, 150, 300, 250]
        for t in times:
            perf_service.update_performance('test', t, True)

        profile = perf_service.get_profile('test')
        assert profile.avg_response_time == 200.0  # (100+200+150+300+250)/5
        assert profile.min_response_time == 100.0
        assert profile.max_response_time == 300.0

    # =====================================================================
    # Adaptive Timeout Tests
    # =====================================================================

    def test_get_adaptive_timeout_new_container(self, perf_service):
        """Test adaptive timeout for container without history"""
        timeout = perf_service.get_adaptive_timeout('new_container')

        config = perf_service.get_config()
        assert timeout >= config.default_timeout
        assert timeout <= config.max_timeout

    def test_get_adaptive_timeout_fast_container(self, perf_service):
        """Test adaptive timeout for fast container"""
        # Create fast container profile (100ms avg)
        for t in [80, 90, 100, 110, 120]:
            perf_service.update_performance('fast', t, True)

        timeout = perf_service.get_adaptive_timeout('fast')
        config = perf_service.get_config()

        # Fast containers use min timeout
        assert timeout >= config.min_timeout  # Should be at least minimum
        assert timeout <= config.max_timeout  # Never above max
        assert timeout < config.default_timeout  # Should be faster than default

    def test_get_adaptive_timeout_slow_container(self, perf_service):
        """Test adaptive timeout for slow container"""
        # Create slow container profile (3000ms avg)
        for t in [2800, 2900, 3000, 3100, 3200]:
            perf_service.update_performance('slow', t, True)

        timeout = perf_service.get_adaptive_timeout('slow')

        # Should be higher for slow containers
        assert timeout > 3000

    def test_get_adaptive_timeout_unreliable_container(self, perf_service):
        """Test adaptive timeout for unreliable container (low success rate)"""
        # Create unreliable container (50% success rate)
        perf_service.update_performance('unreliable', 1000, True)
        perf_service.update_performance('unreliable', 0, False)
        perf_service.update_performance('unreliable', 1000, True)
        perf_service.update_performance('unreliable', 0, False)

        timeout = perf_service.get_adaptive_timeout('unreliable')

        # Should be higher to accommodate unreliability
        assert timeout > 1000

    # =====================================================================
    # Container Classification Tests
    # =====================================================================

    def test_classify_containers_mixed(self, perf_service):
        """Test classification of mixed fast/slow containers"""
        # Fast container (avg < 8s)
        for t in [100, 150, 120]:
            perf_service.update_performance('fast1', t, True)

        # Slow container (avg >= 8s)
        for t in [8000, 8500, 9000]:
            perf_service.update_performance('slow1', t, True)

        # Unknown container (no history)
        # 'unknown1' - no data added

        classification = perf_service.classify_containers(['fast1', 'slow1', 'unknown1'])

        assert 'fast1' in classification.fast_containers
        assert 'slow1' in classification.slow_containers
        assert 'unknown1' in classification.unknown_containers

    def test_classify_containers_all_fast(self, perf_service):
        """Test classification when all containers are fast"""
        for name in ['fast1', 'fast2', 'fast3']:
            for t in [100, 150, 120]:
                perf_service.update_performance(name, t, True)

        classification = perf_service.classify_containers(['fast1', 'fast2', 'fast3'])

        assert len(classification.fast_containers) == 3
        assert len(classification.slow_containers) == 0
        assert len(classification.unknown_containers) == 0

    def test_classify_containers_empty_list(self, perf_service):
        """Test classification with empty container list"""
        classification = perf_service.classify_containers([])

        assert classification.total_containers == 0


class TestDockerStatusFetchService:
    """Test suite for DockerStatusFetchService"""

    @pytest.fixture
    def fetch_service(self):
        """Get clean DockerStatusFetchService instance"""
        service = get_fetch_service()
        service.clear_query_history()
        return service

    # =====================================================================
    # Successful Fetch Tests
    # =====================================================================

    @pytest.mark.asyncio
    async def test_fetch_with_retries_success_first_attempt(self, fetch_service):
        """Test successful fetch on first attempt"""
        mock_info = {'State': {'Running': True, 'Status': 'running'}}
        mock_stats = None

        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=mock_stats):

                container_name, info, stats = await fetch_service.fetch_with_retries('test_container')

                assert container_name == 'test_container'
                assert info == mock_info
                assert stats == mock_stats

    @pytest.mark.asyncio
    async def test_fetch_with_retries_includes_stats(self, fetch_service):
        """Test that fetch includes both info and stats"""
        mock_info = {
            'State': {'Running': True},
            '_computed': {
                'cpu_percent': 10.5,
                'memory_usage_mb': 256.0,
                'uptime_seconds': 3600
            }
        }

        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, return_value=mock_info):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=None):

                container_name, info, stats = await fetch_service.fetch_with_retries('test')

                assert info == mock_info
                assert '_computed' in info

    # =====================================================================
    # Retry Logic Tests
    # =====================================================================

    @pytest.mark.asyncio
    async def test_fetch_with_retries_exception_in_info(self, fetch_service):
        """Test that exceptions in info fetch are returned (not retried due to return_exceptions=True)"""
        mock_error = RuntimeError('Docker daemon error')
        mock_info = {'State': {'Running': True}}

        # First call raises error - due to return_exceptions=True, this becomes the return value
        info_mock = AsyncMock()
        info_mock.return_value = mock_error

        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first', info_mock):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=None):

                container_name, info, stats = await fetch_service.fetch_with_retries('test')

                # Exception is returned as value (due to return_exceptions=True in gather)
                assert container_name == 'test'
                assert info == mock_error or isinstance(info, Exception)

    @pytest.mark.asyncio
    async def test_fetch_with_retries_all_timeout(self, fetch_service):
        """Test behavior when all retries timeout"""
        # Mock that always times out
        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first',
                   new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):
                with patch.object(fetch_service, '_emergency_full_fetch',
                                  new_callable=AsyncMock,
                                  return_value=('test', Exception('All timeouts'), None)):

                    container_name, info, stats = await fetch_service.fetch_with_retries('test')

                    # Should call emergency fetch after retries fail
                    assert container_name == 'test'
                    assert isinstance(info, Exception)

    @pytest.mark.asyncio
    async def test_fetch_with_retries_exception_handling(self, fetch_service):
        """Test that exceptions are returned as values (due to return_exceptions=True)"""
        mock_error = RuntimeError('Docker error')

        # Exception is returned as value (not raised) due to return_exceptions=True
        info_mock = AsyncMock()
        info_mock.return_value = mock_error

        with patch('services.docker_status.fetch_service.get_docker_info_dict_service_first', info_mock):
            with patch('services.docker_status.fetch_service.get_docker_stats_service_first',
                       new_callable=AsyncMock, return_value=None):

                container_name, info, stats = await fetch_service.fetch_with_retries('test')

                # Exception is returned as value, not raised
                assert isinstance(info, Exception) or info == mock_error

    # =====================================================================
    # Query Cooldown Tests
    # =====================================================================

    def test_get_query_cooldown(self, fetch_service):
        """Test getting query cooldown value"""
        cooldown = fetch_service.get_query_cooldown()
        assert isinstance(cooldown, int)
        assert cooldown >= 0

    def test_set_query_cooldown(self, fetch_service):
        """Test setting query cooldown value"""
        original = fetch_service.get_query_cooldown()

        fetch_service.set_query_cooldown(5)
        assert fetch_service.get_query_cooldown() == 5

        # Restore original
        fetch_service.set_query_cooldown(original)


class TestConditionalUpdateCacheService:
    """Test suite for ConditionalUpdateCacheService"""

    @pytest.fixture
    def cache_service(self):
        """Get clean ConditionalUpdateCacheService instance"""
        service = get_conditional_cache_service()
        service.clear_cache()
        service.reset_statistics()
        return service

    # =====================================================================
    # Content Change Detection Tests
    # =====================================================================

    def test_has_content_changed_first_time(self, cache_service):
        """Test content change detection for first-time content"""
        content = {'description': 'test', 'color': 123}

        # First time should always return True (content changed)
        assert cache_service.has_content_changed('key1', content) is True

    def test_has_content_changed_identical_content(self, cache_service):
        """Test that identical content is detected as unchanged"""
        content = {'description': 'test', 'color': 123}

        # First update
        cache_service.update_content('key1', content)

        # Second check with same content
        assert cache_service.has_content_changed('key1', content) is False

    def test_has_content_changed_different_content(self, cache_service):
        """Test that different content is detected as changed"""
        content1 = {'description': 'test1', 'color': 123}
        content2 = {'description': 'test2', 'color': 456}

        cache_service.update_content('key1', content1)

        # Content changed
        assert cache_service.has_content_changed('key1', content2) is True

    def test_has_content_changed_partial_change(self, cache_service):
        """Test detection when only part of content changes"""
        content1 = {'description': 'test', 'color': 123, 'footer': 'v1'}
        content2 = {'description': 'test', 'color': 123, 'footer': 'v2'}

        cache_service.update_content('key1', content1)

        # Footer changed
        assert cache_service.has_content_changed('key1', content2) is True

    # =====================================================================
    # Update Content Tests
    # =====================================================================

    def test_update_content(self, cache_service):
        """Test updating cached content"""
        content = {'description': 'test', 'color': 123}

        cache_service.update_content('key1', content)

        # Should now be cached
        assert cache_service.has_content_changed('key1', content) is False

    def test_update_content_multiple_keys(self, cache_service):
        """Test caching multiple different keys"""
        content1 = {'description': 'test1'}
        content2 = {'description': 'test2'}

        cache_service.update_content('key1', content1)
        cache_service.update_content('key2', content2)

        assert cache_service.has_content_changed('key1', content1) is False
        assert cache_service.has_content_changed('key2', content2) is False

    # =====================================================================
    # Statistics Tests
    # =====================================================================

    def test_statistics_tracking(self, cache_service):
        """Test that statistics are tracked correctly"""
        content = {'description': 'test'}

        # First time - content changed (sent)
        cache_service.has_content_changed('key1', content)
        cache_service.update_content('key1', content)

        # Second time - content unchanged (skipped)
        cache_service.has_content_changed('key1', content)

        stats = cache_service.get_statistics()
        assert stats['total'] >= 2
        assert stats['cache_size'] >= 1

    def test_reset_statistics(self, cache_service):
        """Test resetting statistics"""
        content = {'description': 'test'}
        cache_service.has_content_changed('key1', content)
        cache_service.update_content('key1', content)

        cache_service.reset_statistics()

        stats = cache_service.get_statistics()
        assert stats['skipped'] == 0
        assert stats['sent'] == 0
        assert stats['total'] == 0

    def test_clear_cache(self, cache_service):
        """Test clearing the entire cache"""
        cache_service.update_content('key1', {'test': 1})
        cache_service.update_content('key2', {'test': 2})

        cache_service.clear_cache()

        # All content should now be "changed" since cache is empty
        assert cache_service.has_content_changed('key1', {'test': 1}) is True
        assert cache_service.has_content_changed('key2', {'test': 2}) is True

    # =====================================================================
    # Performance Tests
    # =====================================================================

    def test_cache_performance_benefit(self, cache_service):
        """Test that caching provides performance benefit"""
        content = {'description': 'test' * 1000}  # Large content

        # First time - should trigger change detection
        cache_service.has_content_changed('key1', content)
        cache_service.update_content('key1', content)

        # Measure cached checks
        iterations = 100
        start = time.time()
        for _ in range(iterations):
            cache_service.has_content_changed('key1', content)
        total_cached_time = time.time() - start

        # Cached checks should complete (even lots of them should be fast)
        avg_cached_check_time = total_cached_time / iterations
        assert avg_cached_check_time < 0.001  # Each check should be under 1ms


# =========================================================================
# Test Configuration
# =========================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
