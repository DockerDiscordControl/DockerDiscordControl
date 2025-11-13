# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Performance Metrics Logging                    #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Lightweight performance metrics logging system for DDC.

This module provides simple performance monitoring without external dependencies
like Prometheus/Grafana. Metrics are logged to JSON files and can be viewed via
Web UI or command line.

Usage:
    from utils.performance_metrics import PerformanceMetrics

    # Track an operation
    with PerformanceMetrics.track("config_load"):
        config = load_config()

    # Manual tracking
    metrics = PerformanceMetrics()
    metrics.start("docker_operation")
    # ... do work ...
    metrics.end("docker_operation", success=True, metadata={"container": "nginx"})

    # Get statistics
    stats = PerformanceMetrics.get_stats("config_load")
"""

import time
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from contextlib import contextmanager
import threading

logger = logging.getLogger("ddc.performance_metrics")


@dataclass
class MetricEntry:
    """Single performance metric entry."""
    operation: str
    start_time: float
    end_time: float
    duration: float
    success: bool
    timestamp: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class MetricStats:
    """Performance statistics for an operation."""
    operation: str
    total_calls: int
    successful_calls: int
    failed_calls: int
    min_duration: float
    max_duration: float
    avg_duration: float
    p50_duration: float
    p95_duration: float
    p99_duration: float
    last_24h_calls: int
    last_hour_calls: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class PerformanceMetrics:
    """Lightweight performance metrics tracking."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize performance metrics."""
        if not hasattr(self, '_initialized'):
            self.metrics_dir = Path("data/metrics")
            self.metrics_dir.mkdir(parents=True, exist_ok=True)
            self.metrics_file = self.metrics_dir / "performance_metrics.jsonl"
            self.current_operations: Dict[str, float] = {}
            self._initialized = True
            logger.debug("Performance metrics system initialized")

    def start(self, operation: str) -> None:
        """Start tracking an operation."""
        self.current_operations[operation] = time.time()

    def end(self, operation: str, success: bool = True, metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        End tracking an operation and log the metric.

        Args:
            operation: Operation name
            success: Whether operation succeeded
            metadata: Additional metadata

        Returns:
            Duration in seconds
        """
        if operation not in self.current_operations:
            logger.warning(f"Operation '{operation}' not started, cannot end tracking")
            return 0.0

        start_time = self.current_operations.pop(operation)
        end_time = time.time()
        duration = end_time - start_time

        # Create metric entry
        entry = MetricEntry(
            operation=operation,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            success=success,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {}
        )

        # Log to file
        self._write_metric(entry)

        return duration

    def _write_metric(self, entry: MetricEntry) -> None:
        """Write metric entry to JSONL file."""
        try:
            with open(self.metrics_file, 'a') as f:
                f.write(json.dumps(entry.to_dict()) + '\n')
        except (IOError, OSError, PermissionError, json.JSONEncodeError) as e:
            logger.error(f"Failed to write metric: {e}", exc_info=True)

    @contextmanager
    def track(self, operation: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Context manager for tracking operations.

        Usage:
            with PerformanceMetrics().track("config_load"):
                config = load_config()
        """
        self.start(operation)
        success = True
        try:
            yield
        except BaseException as e:
            success = False
            if metadata is None:
                metadata = {}
            metadata['error'] = str(e)
            raise
        finally:
            self.end(operation, success=success, metadata=metadata)

    def get_stats(self, operation: Optional[str] = None, last_hours: int = 24) -> Dict[str, MetricStats]:
        """
        Get performance statistics.

        Args:
            operation: Specific operation name (None for all)
            last_hours: Only include metrics from last N hours

        Returns:
            Dictionary of operation name to MetricStats
        """
        if not self.metrics_file.exists():
            return {}

        # Read metrics
        metrics: Dict[str, List[MetricEntry]] = {}
        cutoff_time = time.time() - (last_hours * 3600)

        try:
            with open(self.metrics_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if data['end_time'] < cutoff_time:
                            continue

                        op = data['operation']
                        if operation and op != operation:
                            continue

                        if op not in metrics:
                            metrics[op] = []

                        metrics[op].append(MetricEntry(**data))
                    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
                        logger.warning(f"Failed to parse metric line: {e}", exc_info=True)
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"Failed to read metrics file: {e}", exc_info=True)
            return {}

        # Calculate statistics
        stats = {}
        for op, entries in metrics.items():
            stats[op] = self._calculate_stats(op, entries)

        return stats

    def _calculate_stats(self, operation: str, entries: List[MetricEntry]) -> MetricStats:
        """Calculate statistics for an operation."""
        if not entries:
            return MetricStats(
                operation=operation,
                total_calls=0,
                successful_calls=0,
                failed_calls=0,
                min_duration=0.0,
                max_duration=0.0,
                avg_duration=0.0,
                p50_duration=0.0,
                p95_duration=0.0,
                p99_duration=0.0,
                last_24h_calls=0,
                last_hour_calls=0
            )

        durations = sorted([e.duration for e in entries])
        successful = sum(1 for e in entries if e.success)
        failed = len(entries) - successful

        # Time windows
        now = time.time()
        last_24h = sum(1 for e in entries if e.end_time > now - (24 * 3600))
        last_hour = sum(1 for e in entries if e.end_time > now - 3600)

        # Percentiles
        def percentile(data, p):
            if not data:
                return 0.0
            k = (len(data) - 1) * p
            f = int(k)
            c = int(k) + 1 if k < len(data) - 1 else int(k)
            return data[f] + (data[c] - data[f]) * (k - f)

        return MetricStats(
            operation=operation,
            total_calls=len(entries),
            successful_calls=successful,
            failed_calls=failed,
            min_duration=min(durations),
            max_duration=max(durations),
            avg_duration=sum(durations) / len(durations),
            p50_duration=percentile(durations, 0.50),
            p95_duration=percentile(durations, 0.95),
            p99_duration=percentile(durations, 0.99),
            last_24h_calls=last_24h,
            last_hour_calls=last_hour
        )

    def get_recent_metrics(self, operation: Optional[str] = None, limit: int = 100) -> List[MetricEntry]:
        """
        Get recent metric entries.

        Args:
            operation: Filter by operation name
            limit: Maximum number of entries to return

        Returns:
            List of recent MetricEntry objects
        """
        if not self.metrics_file.exists():
            return []

        entries = []
        try:
            with open(self.metrics_file, 'r') as f:
                lines = f.readlines()
                # Read from end
                for line in reversed(lines[-limit:]):
                    try:
                        data = json.loads(line.strip())
                        if operation and data['operation'] != operation:
                            continue
                        entries.append(MetricEntry(**data))

                        if len(entries) >= limit:
                            break
                    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
                        logger.warning(f"Failed to parse metric line: {e}", exc_info=True)
        except (IOError, OSError, PermissionError) as e:
            logger.error(f"Failed to read metrics file: {e}", exc_info=True)

        return entries

    def cleanup_old_metrics(self, days: int = 30) -> int:
        """
        Remove metrics older than N days.

        Args:
            days: Number of days to keep

        Returns:
            Number of metrics removed
        """
        if not self.metrics_file.exists():
            return 0

        cutoff_time = time.time() - (days * 24 * 3600)
        temp_file = self.metrics_file.with_suffix('.tmp')
        removed_count = 0
        kept_count = 0

        try:
            with open(self.metrics_file, 'r') as f_in, open(temp_file, 'w') as f_out:
                for line in f_in:
                    try:
                        data = json.loads(line.strip())
                        if data['end_time'] >= cutoff_time:
                            f_out.write(line)
                            kept_count += 1
                        else:
                            removed_count += 1
                    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
                        logger.warning(f"Failed to parse metric line during cleanup: {e}", exc_info=True)

            # Replace original file
            temp_file.replace(self.metrics_file)
            logger.info(f"Cleaned up {removed_count} old metrics, kept {kept_count}")
            return removed_count

        except (IOError, OSError, PermissionError) as e:
            logger.error(f"Failed to cleanup old metrics: {e}", exc_info=True)
            if temp_file.exists():
                temp_file.unlink()
            return 0

    def export_to_json(self, output_file: Path, operation: Optional[str] = None) -> bool:
        """
        Export metrics to a JSON file.

        Args:
            output_file: Output file path
            operation: Filter by operation name

        Returns:
            True if successful
        """
        stats = self.get_stats(operation=operation)

        export_data = {
            'exported_at': datetime.now().isoformat(),
            'operation_filter': operation,
            'statistics': {op: s.to_dict() for op, s in stats.items()}
        }

        try:
            with open(output_file, 'w') as f:
                json.dump(export_data, f, indent=2)
            logger.info(f"Exported metrics to {output_file}")
            return True
        except (IOError, OSError, PermissionError, json.JSONEncodeError) as e:
            logger.error(f"Failed to export metrics: {e}", exc_info=True)
            return False


# Singleton instance
_metrics_instance = None


def get_performance_metrics() -> PerformanceMetrics:
    """Get singleton PerformanceMetrics instance."""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = PerformanceMetrics()
    return _metrics_instance
