# DDC Performance Testing & Monitoring

Complete guide to performance testing, monitoring, and optimization for DockerDiscordControl.

## Table of Contents

- [Overview](#overview)
- [Performance Tests](#performance-tests)
- [Performance Baselines](#performance-baselines)
- [CI/CD Performance Gates](#cicd-performance-gates)
- [Performance Metrics Logging](#performance-metrics-logging)
- [Running Performance Tests](#running-performance-tests)
- [Interpreting Results](#interpreting-results)
- [Optimization Guide](#optimization-guide)

## Overview

DDC includes comprehensive performance testing and monitoring:

- **Automated Performance Tests**: pytest-benchmark based tests for all critical services
- **Performance Baselines**: Defined thresholds for acceptable performance
- **CI/CD Performance Gates**: Automated checks in GitHub Actions
- **Lightweight Metrics Logging**: Simple JSON-based performance tracking
- **Memory Profiling**: Detection of memory leaks and excessive usage

### What's Tested

1. **ConfigService**: Configuration loading, caching, token encryption/decryption
2. **Docker Async Queue**: Queue performance, concurrent operations, timeout handling
3. **MechService**: Power calculations, evolution calculations, state management
4. **DonationService**: API calls, donation calculations (in legacy tests)
5. **Web UI**: Login, dashboard, API endpoints (in legacy tests)

## Performance Tests

### Test Structure

```
tests/performance/
├── test_config_service_performance.py       # ConfigService tests
├── test_docker_async_queue_performance.py   # Docker Async Queue tests
├── test_mech_service_performance.py         # MechService tests
├── test_bootstrap_performance.py            # Bootstrap performance tests
└── legacy/                                  # Legacy tests (archived)
    ├── test_performance_legacy.py
    └── test_docker_pool_performance_legacy.py
```

### ConfigService Performance Tests

**File**: `tests/performance/test_config_service_performance.py`

Tests:
- `test_config_loading_performance`: Benchmark configuration loading
- `test_cached_config_performance`: Benchmark cached configuration access
- `test_cache_vs_no_cache_performance`: Compare cached vs uncached performance
- `test_token_encryption_performance`: Benchmark token encryption
- `test_token_decryption_performance`: Benchmark token decryption
- `test_concurrent_config_access`: Test performance under concurrent access
- `test_config_reload_performance`: Test force reload performance
- `test_memory_usage_with_large_config`: Test memory usage with large configs
- `test_scalability_with_container_count`: Test how service scales with container count

**Expected Performance**:
- Config load: < 1.0s
- Cached config access: < 100ms
- Token encryption/decryption: < 500ms
- Cache speedup: > 2x

### Docker Async Queue Performance Tests

**File**: `tests/performance/test_docker_async_queue_performance.py`

Tests:
- `test_async_client_acquisition_performance`: Benchmark client acquisition
- `test_concurrent_async_operations`: Test concurrent operation handling
- `test_queue_stress_test`: Stress test with many concurrent requests
- `test_container_status_performance`: Benchmark container status retrieval
- `test_container_action_performance`: Benchmark container action execution
- `test_timeout_handling_performance`: Test timeout handling performance
- `test_memory_usage_async_operations`: Test memory usage during async operations

**Expected Performance**:
- Client acquisition: < 500ms
- Concurrent success rate: > 95%
- Queue throughput: > 10 ops/sec
- Memory increase: < 50MB for 100 operations

### MechService Performance Tests

**File**: `tests/performance/test_mech_service_performance.py`

Tests:
- `test_get_state_performance`: Benchmark getting mech state
- `test_power_calculation_performance`: Benchmark power calculation
- `test_evolution_calculation_performance`: Benchmark evolution level calculation
- `test_continuous_power_decay_calculation`: Test continuous power decay
- `test_evolution_thresholds_performance`: Test evolution threshold calculations
- `test_next_evolution_calculation_performance`: Test next evolution cost calculation
- `test_concurrent_state_access`: Test performance under concurrent access
- `test_memory_usage_power_calculations`: Test memory usage during calculations

**Expected Performance**:
- Power calculation: < 1ms
- Evolution calculation: < 1ms
- State access: < 100ms
- Calculations per second: > 1000

## Performance Baselines

Defined in `pytest.ini` under `[performance:thresholds]`:

### ConfigService Baselines

```ini
config_load_max_time = 1.0          # Maximum 1 second for config load
config_cached_max_time = 0.1        # Maximum 100ms for cached config access
token_encrypt_max_time = 0.5        # Maximum 500ms for token encryption
token_decrypt_max_time = 0.5        # Maximum 500ms for token decryption
```

### Docker Async Queue Baselines

```ini
docker_client_acquire_max = 0.5     # Maximum 500ms to acquire client
docker_concurrent_success = 0.95    # Minimum 95% success rate
docker_queue_throughput_min = 10    # Minimum 10 operations/second
```

### MechService Baselines

```ini
mech_power_calc_max = 0.001         # Maximum 1ms for power calculation
mech_evolution_calc_max = 0.001     # Maximum 1ms for evolution calculation
mech_state_access_max = 0.1         # Maximum 100ms for state access
```

### Memory Baselines

```ini
memory_increase_max_mb = 100        # Maximum 100MB memory increase
memory_leak_threshold_mb = 50       # Maximum 50MB for potential leak detection
```

### Concurrent Operation Baselines

```ini
concurrent_success_rate = 0.95      # Minimum 95% success rate
concurrent_avg_duration = 0.5       # Maximum 500ms average duration
concurrent_throughput_min = 20      # Minimum 20 operations/second
```

## CI/CD Performance Gates

**Workflow File**: `.github/workflows/performance-tests.yml`

### Triggers

- Push to `main`, `v2.0`, or `develop` branches
- Pull requests to `main` or `v2.0`
- Manual workflow dispatch

### Jobs

#### 1. Performance Tests

Runs on Python 3.9, 3.10, and 3.11:

```bash
python -m pytest tests/performance/ \
  -m performance \
  --benchmark-only \
  --benchmark-autosave \
  --benchmark-compare-fail=mean:10%  # Fail if 10% slower
```

#### 2. Performance Comparison

Compares PR performance vs main branch:

```bash
python -m pytest tests/performance/ \
  --benchmark-compare=benchmark-main.json \
  --benchmark-compare=benchmark-pr.json \
  --benchmark-compare-fail=mean:20%  # Fail if PR is 20% slower
```

#### 3. Memory Profiling

Checks for memory leaks:

```bash
python -m pytest tests/performance/ \
  -k "memory_leak" \
  -m performance
```

#### 4. Performance Dashboard

Updates performance report on main/v2.0 branches.

### Performance Gates

Build **fails** if:
- Any test exceeds baseline threshold by > 10%
- PR is > 20% slower than main branch
- Memory leak detected (> 50MB increase)
- Success rate < 95%

## Performance Metrics Logging

**Module**: `utils/performance_metrics.py`

Lightweight JSON-based performance tracking without external dependencies.

### Usage

**Context Manager** (recommended):

```python
from utils.performance_metrics import get_performance_metrics

metrics = get_performance_metrics()

# Track an operation
with metrics.track("config_load"):
    config = load_config()

# With metadata
with metrics.track("docker_operation", metadata={"container": "nginx"}):
    result = execute_action("nginx", "restart")
```

**Manual Tracking**:

```python
metrics = get_performance_metrics()

# Start tracking
metrics.start("my_operation")

# ... do work ...

# End tracking
duration = metrics.end("my_operation", success=True, metadata={"key": "value"})
```

### Getting Statistics

```python
# Get stats for all operations
all_stats = metrics.get_stats()

# Get stats for specific operation
config_stats = metrics.get_stats(operation="config_load")

# Stats for last 6 hours only
recent_stats = metrics.get_stats(last_hours=6)

# Example output:
# {
#     'config_load': MetricStats(
#         operation='config_load',
#         total_calls=150,
#         successful_calls=148,
#         failed_calls=2,
#         min_duration=0.050,
#         max_duration=1.200,
#         avg_duration=0.350,
#         p50_duration=0.300,
#         p95_duration=0.800,
#         p99_duration=1.100,
#         last_24h_calls=150,
#         last_hour_calls=25
#     )
# }
```

### Viewing Recent Metrics

```python
# Get recent metric entries
recent = metrics.get_recent_metrics(operation="docker_operation", limit=50)

for entry in recent:
    print(f"{entry.timestamp}: {entry.operation} took {entry.duration:.3f}s")
    if entry.metadata:
        print(f"  Metadata: {entry.metadata}")
```

### Cleanup and Export

```python
# Remove metrics older than 30 days
removed = metrics.cleanup_old_metrics(days=30)

# Export metrics to JSON
metrics.export_to_json(Path("metrics_export.json"), operation="config_load")
```

### Metrics File Location

Metrics are stored in: `data/metrics/performance_metrics.jsonl`

Format: JSON Lines (one JSON object per line):

```json
{"operation": "config_load", "start_time": 1699999999.123, "end_time": 1699999999.456, "duration": 0.333, "success": true, "timestamp": "2025-11-12T23:59:59", "metadata": {}}
```

## Running Performance Tests

### Prerequisites

Install test dependencies:

```bash
pip install -r requirements-test.txt
```

This includes:
- `pytest-benchmark>=4.0.0`
- `locust>=2.16.0`
- `memory-profiler>=0.60.0`

### Run All Performance Tests

```bash
python -m pytest tests/performance/ -m performance -v
```

### Run Specific Test Suite

```bash
# ConfigService tests
python -m pytest tests/performance/test_config_service_performance.py -v

# Docker Async Queue tests
python -m pytest tests/performance/test_docker_async_queue_performance.py -v

# MechService tests
python -m pytest tests/performance/test_mech_service_performance.py -v
```

### Run with Benchmarking

```bash
# Run only benchmark tests
python -m pytest tests/performance/ -m performance --benchmark-only

# Save benchmark results
python -m pytest tests/performance/ -m performance --benchmark-autosave

# Compare with previous run
python -m pytest tests/performance/ -m performance --benchmark-compare=0001
```

### Run Memory Profiling Tests

```bash
# Memory usage tests
python -m pytest tests/performance/ -k "memory" -v

# Memory leak detection
python -m pytest tests/performance/ -k "memory_leak" -v
```

### Run Concurrency Tests

```bash
python -m pytest tests/performance/ -k "concurrent" -v
```

### Run with Coverage

```bash
python -m pytest tests/performance/ \
  -m performance \
  --cov=services \
  --cov-report=html \
  --cov-report=term
```

## Interpreting Results

### Benchmark Output

```
================================ test session starts ================================
...
tests/performance/test_config_service_performance.py::TestConfigServicePerformance::test_config_loading_performance

Name (time in ms)                           Min       Max      Mean    StdDev    Median
----------------------------------------------------------------------------------------------
test_config_loading_performance        125.432   145.234   132.123    5.432    130.234
```

**Columns**:
- **Min**: Fastest execution
- **Max**: Slowest execution
- **Mean**: Average execution time
- **StdDev**: Standard deviation (consistency)
- **Median**: Middle value (50th percentile)

**What to Look For**:
- Mean should be below baseline threshold
- Low StdDev means consistent performance
- Max should not be excessive outliers

### Statistics Output

```
ConfigService Performance:
- Uncached (10 loads): 3.245s
- Cached (10 loads): 0.123s
- Speedup: 26.4x
```

**Analysis**:
- Speedup shows effectiveness of caching
- Target: > 2x speedup for caching

### Concurrent Operations Output

```
Concurrent Access Results:
- Workers: 10
- Total reads: 200
- Successful: 200
- Average duration: 0.045s
- Total duration: 2.123s
- Throughput: 94.21 reads/sec
```

**What to Check**:
- Success rate should be 100% (or > 95%)
- Average duration should be low
- Throughput should meet minimum baseline

### Memory Usage Output

```
Memory Usage Test:
- Iterations: 10000
- Memory increase: 15.23MB
```

**Red Flags**:
- Memory increase > 100MB for normal operations
- Steady increase over iterations (potential leak)

## Optimization Guide

### ConfigService Optimization

**Slow Config Loading**:
1. Reduce number of config files
2. Combine small files into larger ones
3. Use caching more aggressively
4. Profile with: `python -m cProfile -s cumtime config_load.py`

**Cache Miss Issues**:
1. Check cache invalidation logic
2. Increase cache TTL if safe
3. Pre-warm cache on startup

### Docker Async Queue Optimization

**High Latency**:
1. Check Docker daemon performance
2. Increase queue size if needed
3. Adjust timeout values in Advanced Settings:
   - `DDC_FAST_STATS_TIMEOUT`
   - `DDC_SLOW_STATS_TIMEOUT`

**Low Throughput**:
1. Check concurrent connection limit (default: 3)
2. Monitor queue depth
3. Check for blocking operations

**Timeouts**:
1. Review timeout configuration
2. Check Docker daemon health
3. Monitor container-specific timeouts

### MechService Optimization

**Slow Calculations**:
1. Check for excessive I/O (state loading)
2. Cache frequently accessed values
3. Optimize power decay calculation

**Memory Usage**:
1. Limit donation history size
2. Implement pagination for large datasets
3. Clean up old metrics regularly

### Web UI Optimization

**Slow Page Loads**:
1. Enable template caching
2. Minimize Docker API calls
3. Use async loading for heavy data

**High Memory Usage**:
1. Limit session count
2. Clear old sessions regularly
3. Optimize template rendering

### General Performance Tips

1. **Use Profiling Tools**:
   ```bash
   python -m cProfile -s cumtime app/web_ui.py
   python -m memory_profiler app/web_ui.py
   ```

2. **Monitor Resource Usage**:
   ```bash
   docker stats dockerdiscordcontrol
   ```

3. **Enable Debug Logging**:
   ```python
   # In config.json
   {
     "scheduler_debug_mode": true
   }
   ```

4. **Regular Cleanup**:
   ```python
   from utils.performance_metrics import get_performance_metrics
   metrics = get_performance_metrics()
   metrics.cleanup_old_metrics(days=30)
   ```

5. **Benchmark Before/After Changes**:
   ```bash
   # Before changes
   python -m pytest tests/performance/ --benchmark-autosave

   # Make changes...

   # After changes
   python -m pytest tests/performance/ --benchmark-compare=0001
   ```

## Continuous Monitoring

### Daily Checks

1. Review CI/CD performance test results
2. Check for performance regressions in PRs
3. Monitor memory usage trends

### Weekly Tasks

1. Review performance metrics dashboard
2. Analyze slow operations in metrics logs
3. Clean up old metrics (> 30 days)

### Monthly Tasks

1. Run full performance test suite locally
2. Update performance baselines if needed
3. Profile critical paths with cProfile
4. Review and optimize slow queries/operations

## Troubleshooting

### Tests Fail in CI but Pass Locally

**Possible Causes**:
- Different Python versions
- Different system resources
- Different Docker daemon performance

**Solutions**:
- Run tests with same Python version as CI
- Increase timeout thresholds slightly
- Check CI logs for specific failures

### High Memory Usage

**Debug**:
```python
import tracemalloc
tracemalloc.start()

# ... run operation ...

snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')

for stat in top_stats[:10]:
    print(stat)
```

### Inconsistent Benchmark Results

**Causes**:
- System load variations
- Background processes
- Thermal throttling

**Solutions**:
- Increase `min_rounds` in pytest.ini
- Run on dedicated hardware
- Close other applications

## See Also

- [SERVICES.md](SERVICES.md) - Service architecture
- [CONFIGURATION.md](CONFIGURATION.md) - Configuration guide
- [ERROR_HANDLING.md](ERROR_HANDLING.md) - Error handling guide
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines
