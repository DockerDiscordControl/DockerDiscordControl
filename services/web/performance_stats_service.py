#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Performance Stats Service                      #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Performance Stats Service - Handles system performance monitoring and statistics collection
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass

try:
    import docker
    import docker.errors
except ImportError:
    docker = None  # Handle missing docker library gracefully

logger = logging.getLogger(__name__)


@dataclass
class PerformanceStatsResult:
    """Represents the result of performance stats collection."""
    success: bool
    performance_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PerformanceStatsService:
    """Service for collecting and formatting system performance statistics."""

    def __init__(self):
        self.logger = logger

    def get_performance_stats(self) -> PerformanceStatsResult:
        """
        Collect comprehensive system performance statistics.

        Returns:
            PerformanceStatsResult with performance data or error information
        """
        try:
            performance_data = {}

            # Collect all performance metrics
            performance_data['config_cache'] = self._get_config_cache_stats()
            performance_data['docker_cache'] = self._get_docker_cache_stats()
            performance_data['scheduler'] = self._get_scheduler_stats()
            performance_data['system_memory'] = self._get_system_memory_stats()
            performance_data['process_memory'] = self._get_process_memory_stats()

            # Add timestamp information
            performance_data['timestamp'] = time.time()
            performance_data['timestamp_formatted'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            return PerformanceStatsResult(
                success=True,
                performance_data=performance_data
            )

        except (RuntimeError) as e:
            self.logger.error(f"Error collecting performance statistics: {e}", exc_info=True)
            return PerformanceStatsResult(
                success=False,
                error=f"Error collecting performance statistics: {str(e)}"
            )

    def _get_config_cache_stats(self) -> Dict[str, Any]:
        """Get configuration cache statistics."""
        try:
            from utils.config_cache import get_cache_memory_stats
            return get_cache_memory_stats()
        except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException) as e:
            self.logger.warning(f"Could not get config cache stats: {e}")
            return {'error': str(e)}

    def _get_docker_cache_stats(self) -> Dict[str, Any]:
        """Get Docker cache statistics with formatted timestamps."""
        try:
            from app.utils.web_helpers import docker_cache, cache_lock

            with cache_lock:
                cache_stats = {
                    'containers_count': len(docker_cache.get('containers', [])),
                    'access_count': docker_cache.get('access_count', 0),
                    'global_timestamp': docker_cache.get('global_timestamp'),
                    'last_cleanup': docker_cache.get('last_cleanup'),
                    'bg_refresh_running': docker_cache.get('bg_refresh_running', False),
                    'priority_containers_count': len(docker_cache.get('priority_containers', set())),
                    'container_timestamps_count': len(docker_cache.get('container_timestamps', {})),
                    'container_hashes_count': len(docker_cache.get('container_hashes', {})),
                    'error': docker_cache.get('error')
                }

                # Format timestamps for readability
                if cache_stats['global_timestamp']:
                    cache_stats['global_timestamp_formatted'] = datetime.fromtimestamp(
                        cache_stats['global_timestamp']
                    ).strftime('%Y-%m-%d %H:%M:%S')

                if cache_stats['last_cleanup']:
                    cache_stats['last_cleanup_formatted'] = datetime.fromtimestamp(
                        cache_stats['last_cleanup']
                    ).strftime('%Y-%m-%d %H:%M:%S')

            return cache_stats
        except (AttributeError, KeyError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException) as e:
            self.logger.warning(f"Could not get Docker cache stats: {e}")
            return {'error': str(e)}

    def _get_scheduler_stats(self) -> Dict[str, Any]:
        """Get scheduler service statistics."""
        try:
            from services.scheduling.scheduler_service import get_scheduler_stats
            return get_scheduler_stats()
        except (AttributeError, ImportError, KeyError, ModuleNotFoundError, RuntimeError, TypeError) as e:
            self.logger.warning(f"Could not get scheduler stats: {e}")
            return {'error': str(e)}

    def _get_system_memory_stats(self) -> Dict[str, Any]:
        """Get system memory information."""
        try:
            import psutil
            memory = psutil.virtual_memory()
            return {
                'total_mb': round(memory.total / (1024 * 1024), 2),
                'available_mb': round(memory.available / (1024 * 1024), 2),
                'percent_used': memory.percent,
                'free_mb': round(memory.free / (1024 * 1024), 2)
            }
        except (RuntimeError) as e:
            self.logger.warning(f"Could not get system memory stats: {e}")
            return {'error': str(e)}

    def _get_process_memory_stats(self) -> Dict[str, Any]:
        """Get current process memory usage."""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return {
                'rss_mb': round(memory_info.rss / (1024 * 1024), 2),
                'vms_mb': round(memory_info.vms / (1024 * 1024), 2),
                'percent': round(process.memory_percent(), 2),
                'num_threads': process.num_threads()
            }
        except (IOError, OSError, PermissionError, RuntimeError) as e:
            self.logger.warning(f"Could not get process memory stats: {e}")
            return {'error': str(e)}


# Singleton instance
_performance_stats_service = None


def get_performance_stats_service() -> PerformanceStatsService:
    """Get the singleton PerformanceStatsService instance."""
    global _performance_stats_service
    if _performance_stats_service is None:
        _performance_stats_service = PerformanceStatsService()
    return _performance_stats_service