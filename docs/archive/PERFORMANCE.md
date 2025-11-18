# DDC Performance Monitoring

Complete guide to performance monitoring and optimization for DockerDiscordControl.

## Table of Contents

- [Overview](#overview)
- [Performance Metrics Logging](#performance-metrics-logging)
- [Optimization Guide](#optimization-guide)

## Overview

DDC includes lightweight performance monitoring:

- **Lightweight Metrics Logging**: Simple JSON-based performance tracking
- **Real-time Metrics Collection**: Track operations, durations, and resource usage

### Services Monitored

1. **ConfigService**: Configuration loading, caching, token encryption/decryption
2. **Docker Async Queue**: Queue performance, concurrent operations, timeout handling
3. **MechService**: Power calculations, evolution calculations, state management
4. **DonationService**: API calls, donation calculations
5. **Web UI**: Login, dashboard, API endpoints

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

5. **Monitor Resource Usage**:
   ```bash
   docker stats dockerdiscordcontrol
   ```

## Continuous Monitoring

### Daily Checks

1. Monitor memory usage trends
2. Review performance metrics logs

### Weekly Tasks

1. Analyze slow operations in metrics logs
2. Clean up old metrics (> 30 days)

### Monthly Tasks

1. Profile critical paths with cProfile
2. Review and optimize slow queries/operations

## Troubleshooting

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

## See Also

- [SERVICES.md](SERVICES.md) - Service architecture
- [CONFIGURATION.md](CONFIGURATION.md) - Configuration guide
- [ERROR_HANDLING.md](ERROR_HANDLING.md) - Error handling guide
- [OBSERVABILITY.md](OBSERVABILITY.md) - Observability and metrics guide
