# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - ConfigService Performance Tests                #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Performance tests for ConfigService.
Tests caching performance, load times, token encryption, and concurrent access.
"""

import pytest
import time
import tempfile
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
import psutil

from services.config.config_service import ConfigService, get_config_service
from services.config.config_cache_service import ConfigCacheService
from services.config.config_loader_service import ConfigLoaderService


@pytest.mark.performance
class TestConfigServicePerformance:
    """Performance tests for ConfigService."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir) / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Create test config files
        self._create_test_config_files()

    def teardown_method(self):
        """Cleanup test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _get_test_config_service(self):
        """Get ConfigService instance configured for testing.

        FIX: ConfigService is a singleton that doesn't accept config_dir parameter.
        We override the paths after getting the singleton instance.
        """
        service = get_config_service()

        # Override all directory paths
        service.config_dir = self.config_dir
        service.channels_dir = self.config_dir / "channels"
        service.containers_dir = self.config_dir / "containers"

        # Override modular config file paths
        service.main_config_file = self.config_dir / "config.json"
        service.auth_config_file = self.config_dir / "auth.json"
        service.heartbeat_config_file = self.config_dir / "heartbeat.json"
        service.web_ui_config_file = self.config_dir / "web_ui.json"
        service.docker_settings_file = self.config_dir / "docker_settings.json"

        # Override legacy config file paths
        service.bot_config_file = self.config_dir / "bot_config.json"
        service.docker_config_file = self.config_dir / "docker_config.json"
        service.web_config_file = self.config_dir / "web_config.json"
        service.channels_config_file = self.config_dir / "channels_config.json"

        # Reinitialize loader with test paths
        service._loader_service = ConfigLoaderService(
            service.config_dir,
            service.channels_dir,
            service.containers_dir,
            service.main_config_file,
            service.auth_config_file,
            service.heartbeat_config_file,
            service.web_ui_config_file,
            service.docker_settings_file,
            service.bot_config_file,
            service.docker_config_file,
            service.web_config_file,
            service.channels_config_file,
            service._load_json_file,
            service._validation_service
        )

        return service

    def _create_test_config_files(self):
        """Create test configuration files."""
        # Main config
        config_file = self.config_dir / "config.json"
        config_file.write_text(json.dumps({
            "language": "en",
            "timezone": "UTC",
            "guild_id": "123456789"
        }))

        # Containers
        containers_dir = self.config_dir / "containers"
        containers_dir.mkdir(exist_ok=True)
        for i in range(50):  # Create 50 test containers
            container_file = containers_dir / f"container_{i:02d}.json"
            container_file.write_text(json.dumps({
                "container_name": f"container_{i:02d}",
                "display_name": f"Test Container {i:02d}",
                "docker_name": f"container_{i:02d}",
                "allowed_actions": ["status", "start", "stop", "restart"],
                "active": True,
                "order": i
            }))

        # Channels
        channels_dir = self.config_dir / "channels"
        channels_dir.mkdir(exist_ok=True)
        for i in range(10):  # Create 10 test channels
            channel_file = channels_dir / f"channel_{i:02d}.json"
            channel_file.write_text(json.dumps({
                "channel_id": f"98765432{i:02d}",
                "name": f"channel-{i:02d}",
                "commands": {
                    "serverstatus": True,
                    "control": i % 2 == 0,
                    "schedule": i % 3 == 0
                }
            }))

    @pytest.mark.benchmark(group="config-load")
    def test_config_loading_performance(self, benchmark):
        """Benchmark configuration loading."""
        service = self._get_test_config_service()

        def load_config():
            return service.get_config(force_reload=True)

        result = benchmark(load_config)
        assert isinstance(result, dict)
        assert 'servers' in result
        assert len(result['servers']) == 50

    @pytest.mark.benchmark(group="config-cache")
    def test_cached_config_performance(self, benchmark):
        """Benchmark cached configuration access."""
        service = self._get_test_config_service()

        # Prime the cache
        service.get_config(force_reload=True)

        def get_cached_config():
            return service.get_config(force_reload=False)

        result = benchmark(get_cached_config)
        assert isinstance(result, dict)

    def test_cache_vs_no_cache_performance(self):
        """Compare cached vs uncached config loading."""
        service = self._get_test_config_service()

        # Test without cache
        start_time = time.time()
        for _ in range(10):
            service.get_config(force_reload=True)
        uncached_duration = time.time() - start_time

        # Test with cache
        start_time = time.time()
        for _ in range(10):
            service.get_config(force_reload=False)
        cached_duration = time.time() - start_time

        speedup = uncached_duration / cached_duration if cached_duration > 0 else 0

        print(f"\nCache Performance:")
        print(f"- Uncached (10 loads): {uncached_duration:.3f}s")
        print(f"- Cached (10 loads): {cached_duration:.3f}s")
        print(f"- Speedup: {speedup:.1f}x")

        # Cache should be significantly faster
        assert cached_duration < uncached_duration
        assert speedup > 2.0  # At least 2x faster with cache

    @pytest.mark.benchmark(group="token-encryption")
    def test_token_encryption_performance(self, benchmark):
        """Benchmark token encryption."""
        from werkzeug.security import generate_password_hash

        service = self._get_test_config_service()
        password_hash = generate_password_hash("test_password")
        plaintext_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTA.ABC123.xyz789-example"

        def encrypt_token():
            return service.encrypt_token(plaintext_token, password_hash)

        result = benchmark(encrypt_token)
        assert result is not None

    @pytest.mark.benchmark(group="token-decryption")
    def test_token_decryption_performance(self, benchmark):
        """Benchmark token decryption."""
        from werkzeug.security import generate_password_hash

        service = self._get_test_config_service()
        password_hash = generate_password_hash("test_password")
        plaintext_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTA.ABC123.xyz789-example"

        # Encrypt first
        encrypted_token = service.encrypt_token(plaintext_token, password_hash)

        def decrypt_token():
            return service.decrypt_token(encrypted_token, password_hash)

        result = benchmark(decrypt_token)
        assert result == plaintext_token

    def test_concurrent_config_access(self):
        """Test performance under concurrent config access."""
        service = self._get_test_config_service()
        max_workers = 10
        reads_per_worker = 20
        results = []

        def worker_task(worker_id):
            worker_results = []
            for i in range(reads_per_worker):
                start_time = time.time()
                config = service.get_config(force_reload=False)
                duration = time.time() - start_time

                worker_results.append({
                    'worker_id': worker_id,
                    'read_id': i,
                    'duration': duration,
                    'success': isinstance(config, dict)
                })

            return worker_results

        # Execute concurrent reads
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker_task, i) for i in range(max_workers)]
            for future in futures:
                results.extend(future.result())
        total_duration = time.time() - start_time

        # Analyze results
        total_reads = len(results)
        successful_reads = sum(1 for r in results if r['success'])
        average_duration = sum(r['duration'] for r in results) / total_reads
        throughput = total_reads / total_duration

        print(f"\nConcurrent Access Results:")
        print(f"- Workers: {max_workers}")
        print(f"- Total reads: {total_reads}")
        print(f"- Successful: {successful_reads}")
        print(f"- Average duration: {average_duration:.3f}s")
        print(f"- Total duration: {total_duration:.3f}s")
        print(f"- Throughput: {throughput:.2f} reads/sec")

        # All reads should succeed
        assert successful_reads == total_reads
        # Average read should be fast
        assert average_duration < 0.1

    def test_config_reload_performance(self):
        """Test performance of force reload."""
        service = self._get_test_config_service()

        reload_times = []

        for i in range(10):
            start_time = time.time()
            config = service.get_config(force_reload=True)
            duration = time.time() - start_time
            reload_times.append(duration)

            assert isinstance(config, dict)

        avg_reload_time = sum(reload_times) / len(reload_times)
        max_reload_time = max(reload_times)
        min_reload_time = min(reload_times)

        print(f"\nConfig Reload Performance:")
        print(f"- Reloads: {len(reload_times)}")
        print(f"- Average: {avg_reload_time:.3f}s")
        print(f"- Min: {min_reload_time:.3f}s")
        print(f"- Max: {max_reload_time:.3f}s")

        # Reloads should complete in reasonable time
        assert avg_reload_time < 1.0
        assert max_reload_time < 2.0

    def test_memory_usage_with_large_config(self):
        """Test memory usage with large configuration."""
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        service = self._get_test_config_service()

        # Load config multiple times
        for _ in range(20):
            config = service.get_config(force_reload=True)
            assert isinstance(config, dict)

        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        print(f"\nMemory Usage Test:")
        print(f"- Initial: {initial_memory / 1024 / 1024:.2f}MB")
        print(f"- Final: {final_memory / 1024 / 1024:.2f}MB")
        print(f"- Increase: {memory_increase / 1024 / 1024:.2f}MB")

        # Memory increase should be reasonable (less than 20MB)
        assert memory_increase < 20 * 1024 * 1024

    @pytest.mark.benchmark(group="container-filtering")
    def test_container_filtering_performance(self, benchmark):
        """Benchmark container filtering (active vs inactive)."""
        service = self._get_test_config_service()
        config = service.get_config(force_reload=True)

        def filter_containers():
            servers = config.get('servers', [])
            active_servers = [s for s in servers if s.get('active', False)]
            return len(active_servers)

        result = benchmark(filter_containers)
        assert result == 50  # All our test containers are active

    def test_scalability_with_container_count(self):
        """Test how config service scales with container count."""
        container_counts = [10, 50, 100, 200]
        performance_metrics = []

        for count in container_counts:
            # Create temp dir with specific number of containers
            temp_dir = tempfile.mkdtemp()
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir(parents=True, exist_ok=True)

            # Create config
            (config_dir / "config.json").write_text(json.dumps({
                "language": "en",
                "timezone": "UTC"
            }))

            # Create containers
            containers_dir = config_dir / "containers"
            containers_dir.mkdir(exist_ok=True)
            for i in range(count):
                (containers_dir / f"container_{i:03d}.json").write_text(json.dumps({
                    "container_name": f"container_{i:03d}",
                    "active": True,
                    "order": i
                }))

            # FIX: ConfigService is singleton - override paths after getting instance
            service = get_config_service()

            # Override all directory paths
            service.config_dir = config_dir
            service.channels_dir = config_dir / "channels"
            service.containers_dir = config_dir / "containers"

            # Override modular config file paths
            service.main_config_file = config_dir / "config.json"
            service.auth_config_file = config_dir / "auth.json"
            service.heartbeat_config_file = config_dir / "heartbeat.json"
            service.web_ui_config_file = config_dir / "web_ui.json"
            service.docker_settings_file = config_dir / "docker_settings.json"

            # Override legacy config file paths
            service.bot_config_file = config_dir / "bot_config.json"
            service.docker_config_file = config_dir / "docker_config.json"
            service.web_config_file = config_dir / "web_config.json"
            service.channels_config_file = config_dir / "channels_config.json"

            # Reinitialize loader with test paths
            service._loader_service = ConfigLoaderService(
                service.config_dir,
                service.channels_dir,
                service.containers_dir,
                service.main_config_file,
                service.auth_config_file,
                service.heartbeat_config_file,
                service.web_ui_config_file,
                service.docker_settings_file,
                service.bot_config_file,
                service.docker_config_file,
                service.web_config_file,
                service.channels_config_file,
                service._load_json_file,
                service._validation_service
            )

            # Measure performance
            start_time = time.time()
            for _ in range(5):
                config = service.get_config(force_reload=True)
                assert len(config.get('servers', [])) == count
            duration = time.time() - start_time
            avg_time = duration / 5

            performance_metrics.append({
                'container_count': count,
                'avg_load_time': avg_time,
                'containers_per_second': count / avg_time if avg_time > 0 else 0
            })

            # Cleanup
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

        print(f"\nScalability Test Results:")
        for metric in performance_metrics:
            print(f"- {metric['container_count']} containers: {metric['avg_load_time']:.3f}s "
                  f"({metric['containers_per_second']:.0f} containers/sec)")

        # Performance should scale reasonably
        for metric in performance_metrics:
            assert metric['avg_load_time'] < 2.0  # Should load in under 2 seconds


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])
