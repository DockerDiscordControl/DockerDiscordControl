# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - MechService Performance Tests                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Performance tests for MechService.
Tests state management, power calculations, evolution calculations, and animation generation.
"""

import pytest
import time
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import psutil
import os

from services.mech.mech_service import MechService
from services.mech.models import MechState


@pytest.mark.performance
class TestMechServicePerformance:
    """Performance tests for MechService."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.temp_dir) / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        """Cleanup test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.benchmark(group="mech-state")
    def test_get_state_performance(self, benchmark):
        """Benchmark getting mech state."""
        service = MechService(data_dir=self.data_dir)

        def get_state():
            return service.get_state()

        result = benchmark(get_state)
        assert isinstance(result, MechState)

    @pytest.mark.benchmark(group="mech-power")
    def test_power_calculation_performance(self, benchmark):
        """Benchmark power calculation."""
        service = MechService(data_dir=self.data_dir)

        def calculate_power():
            state = service.get_state()
            return service.calculate_current_power(state)

        result = benchmark(calculate_power)
        assert isinstance(result, (int, float))

    @pytest.mark.benchmark(group="mech-evolution")
    def test_evolution_calculation_performance(self, benchmark):
        """Benchmark evolution level calculation."""
        service = MechService(data_dir=self.data_dir)

        def calculate_evolution():
            state = service.get_state()
            return service.calculate_evolution_level(state.total_donated)

        result = benchmark(calculate_evolution)
        assert isinstance(result, int)

    def test_continuous_power_decay_calculation(self):
        """Test performance of continuous power decay calculation."""
        service = MechService(data_dir=self.data_dir)

        # Test different donation amounts
        test_amounts = [10.0, 100.0, 1000.0, 10000.0]
        results = []

        for amount in test_amounts:
            # Mock state with specific donation
            with patch.object(service, 'get_state') as mock_get_state:
                mock_state = MechState(
                    total_donated=amount,
                    last_update=time.time() - (30 * 24 * 3600),  # 30 days ago
                    level=1
                )
                mock_get_state.return_value = mock_state

                start_time = time.time()
                iterations = 1000

                for _ in range(iterations):
                    current_power = service.calculate_current_power(mock_state)

                duration = time.time() - start_time
                avg_time = duration / iterations

                results.append({
                    'amount': amount,
                    'duration': duration,
                    'avg_time': avg_time,
                    'calculations_per_sec': iterations / duration if duration > 0 else 0
                })

        print(f"\nPower Decay Calculation Performance:")
        for r in results:
            print(f"- Amount ${r['amount']}: {r['avg_time']*1000:.3f}ms avg "
                  f"({r['calculations_per_sec']:.0f} calc/sec)")

        # All calculations should be fast
        for r in results:
            assert r['avg_time'] < 0.001  # Under 1ms per calculation

    def test_evolution_thresholds_performance(self):
        """Test performance of evolution threshold calculations."""
        service = MechService(data_dir=self.data_dir)

        # Test range of donation amounts
        test_amounts = [float(x) for x in range(0, 100000, 1000)]
        start_time = time.time()

        evolution_levels = []
        for amount in test_amounts:
            level = service.calculate_evolution_level(amount)
            evolution_levels.append(level)

        duration = time.time() - start_time
        avg_time = duration / len(test_amounts)

        print(f"\nEvolution Threshold Performance:")
        print(f"- Test amounts: {len(test_amounts)}")
        print(f"- Total duration: {duration:.3f}s")
        print(f"- Average per calculation: {avg_time*1000:.3f}ms")
        print(f"- Calculations per second: {len(test_amounts)/duration:.0f}")

        # Should handle many calculations quickly
        assert avg_time < 0.001  # Under 1ms per calculation
        assert len(test_amounts) / duration > 1000  # Over 1000 calc/sec

    def test_next_evolution_calculation_performance(self):
        """Test performance of next evolution cost calculation."""
        service = MechService(data_dir=self.data_dir)

        # Test for different current levels
        test_levels = range(1, 21)  # Test levels 1-20
        results = []

        for current_level in test_levels:
            start_time = time.time()
            iterations = 1000

            for _ in range(iterations):
                next_cost = service.calculate_next_evolution_cost(current_level)

            duration = time.time() - start_time
            avg_time = duration / iterations

            results.append({
                'level': current_level,
                'avg_time': avg_time,
                'calculations_per_sec': iterations / duration if duration > 0 else 0
            })

        print(f"\nNext Evolution Calculation Performance:")
        for r in results[:5]:  # Show first 5
            print(f"- Level {r['level']}: {r['avg_time']*1000:.3f}ms avg "
                  f"({r['calculations_per_sec']:.0f} calc/sec)")

        # All should be fast
        for r in results:
            assert r['avg_time'] < 0.001  # Under 1ms

    @pytest.mark.benchmark(group="mech-state-update")
    def test_state_update_performance(self, benchmark):
        """Benchmark state update operations."""
        service = MechService(data_dir=self.data_dir)

        def update_state():
            state = service.get_state()
            new_state = MechState(
                total_donated=state.total_donated + 10.0,
                last_update=time.time(),
                level=state.level
            )
            return service.save_state(new_state)

        result = benchmark(update_state)

    def test_concurrent_state_access(self):
        """Test performance under concurrent state access."""
        from concurrent.futures import ThreadPoolExecutor

        service = MechService(data_dir=self.data_dir)
        max_workers = 10
        reads_per_worker = 50
        results = []

        def worker_task(worker_id):
            worker_results = []
            for i in range(reads_per_worker):
                start_time = time.time()
                state = service.get_state()
                power = service.calculate_current_power(state)
                duration = time.time() - start_time

                worker_results.append({
                    'worker_id': worker_id,
                    'read_id': i,
                    'duration': duration,
                    'success': isinstance(state, MechState)
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
        total_ops = len(results)
        successful = sum(1 for r in results if r['success'])
        avg_duration = sum(r['duration'] for r in results) / total_ops
        throughput = total_ops / total_duration

        print(f"\nConcurrent State Access:")
        print(f"- Workers: {max_workers}")
        print(f"- Total operations: {total_ops}")
        print(f"- Successful: {successful}")
        print(f"- Average duration: {avg_duration:.3f}s")
        print(f"- Throughput: {throughput:.2f} ops/sec")

        # All should succeed
        assert successful == total_ops
        # Should be fast
        assert avg_duration < 0.1

    def test_memory_usage_power_calculations(self):
        """Test memory usage during repeated power calculations."""
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        service = MechService(data_dir=self.data_dir)

        # Perform many calculations
        iterations = 10000
        state = service.get_state()

        for i in range(iterations):
            power = service.calculate_current_power(state)
            level = service.calculate_evolution_level(state.total_donated)

            # Check memory every 1000 iterations
            if i % 1000 == 0:
                current_memory = process.memory_info().rss
                memory_increase = current_memory - initial_memory
                # Should not leak memory
                assert memory_increase < 20 * 1024 * 1024  # Less than 20MB

        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        print(f"\nMemory Usage Test:")
        print(f"- Iterations: {iterations}")
        print(f"- Memory increase: {memory_increase / 1024 / 1024:.2f}MB")

        # Total memory increase should be minimal
        assert memory_increase < 30 * 1024 * 1024  # Less than 30MB

    def test_animation_generation_performance(self):
        """Test performance of WebP animation generation (if available)."""
        # This is optional since animation generation is expensive
        try:
            from services.mech.animation_service import MechAnimationService
        except ImportError:
            pytest.skip("Animation service not available")

        service = MechAnimationService()

        # Test animation generation for different levels
        test_levels = [1, 5, 10]
        results = []

        for level in test_levels:
            start_time = time.time()

            try:
                # Generate animation (if service supports it)
                animation_path = service.generate_animation(level)
                duration = time.time() - start_time

                results.append({
                    'level': level,
                    'duration': duration,
                    'success': animation_path is not None
                })
            except Exception as e:
                results.append({
                    'level': level,
                    'duration': 0,
                    'success': False,
                    'error': str(e)
                })

        print(f"\nAnimation Generation Performance:")
        for r in results:
            if r['success']:
                print(f"- Level {r['level']}: {r['duration']:.3f}s")
            else:
                print(f"- Level {r['level']}: Failed ({r.get('error', 'Unknown')})")

    def test_donation_history_performance(self):
        """Test performance with large donation history."""
        service = MechService(data_dir=self.data_dir)

        # Simulate large donation history
        donations = []
        for i in range(1000):
            donations.append({
                'amount': 10.0 + (i % 100),
                'timestamp': time.time() - (i * 3600),
                'username': f'user_{i}'
            })

        # Mock the donation history
        with patch.object(service, 'get_donation_history') as mock_history:
            mock_history.return_value = donations

            start_time = time.time()
            iterations = 100

            for _ in range(iterations):
                history = service.get_donation_history()
                total = sum(d['amount'] for d in history)

            duration = time.time() - start_time
            avg_time = duration / iterations

            print(f"\nDonation History Performance:")
            print(f"- History size: {len(donations)}")
            print(f"- Iterations: {iterations}")
            print(f"- Average time: {avg_time:.3f}s")
            print(f"- Operations per second: {iterations/duration:.2f}")

            # Should handle large history efficiently
            assert avg_time < 0.1  # Under 100ms per iteration


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])
