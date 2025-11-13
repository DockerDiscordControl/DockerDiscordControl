# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Observability Utilities                        #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Observability utilities for DDC.

Provides structured logging, metrics collection, and distributed tracing
with OpenTelemetry integration.

Features:
- JSON structured logging
- Lightweight metrics collection (counters, histograms, gauges)
- OpenTelemetry tracing (optional)
- Context propagation
- Service identification

Example:
    >>> from utils.observability import get_structured_logger, metrics
    >>>
    >>> logger = get_structured_logger(__name__)
    >>> logger.info("donation_processed", extra={
    ...     "donor": "John",
    ...     "amount": 5.0,
    ...     "service": "DonationService"
    ... })
    >>>
    >>> metrics.increment("donations.total")
    >>> metrics.histogram("donation.amount", 5.0)
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from contextlib import contextmanager
import sys

# OpenTelemetry imports (optional)
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.trace import Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    trace = None


# ============================================================================ #
# JSON Structured Logging                                                      #
# ============================================================================ #

class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Outputs logs in JSON format with structured fields for easy parsing
    by log aggregation systems (ELK, Loki, etc.).

    Example output:
        {
            "timestamp": "2025-01-15T10:30:45.123Z",
            "level": "INFO",
            "logger": "ddc.donation",
            "message": "donation_processed",
            "service": "DonationService",
            "donor": "John",
            "amount": 5.0,
            "duration_ms": 123.45
        }
    """

    def __init__(self, service_name: str = "ddc"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Base log entry
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }

        # Add extra fields from record
        if hasattr(record, '__dict__'):
            # Add all extra fields that aren't standard logging attributes
            standard_attrs = {
                'name', 'msg', 'args', 'created', 'filename', 'funcName',
                'levelname', 'levelno', 'lineno', 'module', 'msecs',
                'pathname', 'process', 'processName', 'relativeCreated',
                'thread', 'threadName', 'exc_info', 'exc_text', 'stack_info',
                'getMessage', 'message'
            }

            for key, value in record.__dict__.items():
                if key not in standard_attrs:
                    log_entry[key] = value

        # Add source location for debugging
        if record.pathname and record.lineno:
            log_entry["source"] = f"{record.filename}:{record.lineno}"

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


class StructuredLogger(logging.LoggerAdapter):
    """
    Logger adapter that adds structured context to all log messages.

    Allows adding default context that applies to all logs from this logger.

    Example:
        >>> logger = StructuredLogger(logging.getLogger(__name__), {
        ...     "service": "DonationService",
        ...     "component": "processor"
        ... })
        >>> logger.info("Processing donation", extra={"donor": "John"})
    """

    def __init__(self, logger: logging.Logger, extra: Optional[Dict[str, Any]] = None):
        super().__init__(logger, extra or {})

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """Add context to log message."""
        # Merge adapter context with call-specific extra
        extra = kwargs.get('extra', {})
        extra.update(self.extra)
        kwargs['extra'] = extra
        return msg, kwargs


def get_structured_logger(
    name: str,
    service_name: str = "ddc",
    use_json: bool = False,
    context: Optional[Dict[str, Any]] = None
) -> StructuredLogger:
    """
    Get a structured logger with JSON formatting support.

    Args:
        name: Logger name (e.g., __name__)
        service_name: Service name for identification
        use_json: If True, use JSON formatter; otherwise use standard text format
        context: Default context to add to all log messages

    Returns:
        StructuredLogger instance

    Example:
        >>> logger = get_structured_logger(__name__, use_json=True, context={
        ...     "service": "DonationService"
        ... })
        >>> logger.info("donation_processed", extra={"amount": 5.0})
    """
    # Get or create logger
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)

        if use_json:
            formatter = JSONFormatter(service_name)
        else:
            # Use standard formatter
            from utils.logging_utils import DEFAULT_LOG_FORMAT, TimezoneFormatter
            formatter = TimezoneFormatter(DEFAULT_LOG_FORMAT)

        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    # Wrap in StructuredLogger for context support
    return StructuredLogger(logger, context or {})


# ============================================================================ #
# Metrics Collection                                                           #
# ============================================================================ #

class MetricsCollector:
    """
    Lightweight metrics collector for DDC.

    Collects metrics in memory with optional JSON export.
    Supports counters, histograms, and gauges.

    Thread-safe and designed for low overhead.

    Example:
        >>> metrics = MetricsCollector()
        >>> metrics.increment("donations.total")
        >>> metrics.histogram("donation.amount", 5.0)
        >>> metrics.gauge("queue.size", 10)
        >>> stats = metrics.get_stats()
    """

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._gauges: Dict[str, float] = {}
        self._start_time = time.time()

    def increment(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None) -> None:
        """
        Increment a counter metric.

        Args:
            name: Metric name (e.g., "donations.total")
            value: Amount to increment by (default: 1)
            tags: Optional tags for metric (not used in basic implementation)

        Example:
            >>> metrics.increment("api.requests")
            >>> metrics.increment("donations.total", value=1)
        """
        self._counters[name] += value

    def decrement(self, name: str, value: int = 1, tags: Optional[Dict[str, str]] = None) -> None:
        """
        Decrement a counter metric.

        Args:
            name: Metric name
            value: Amount to decrement by (default: 1)
            tags: Optional tags for metric
        """
        self._counters[name] -= value

    def histogram(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """
        Record a value in a histogram.

        Histograms track distributions of values.

        Args:
            name: Metric name (e.g., "donation.amount")
            value: Value to record
            tags: Optional tags for metric

        Example:
            >>> metrics.histogram("donation.amount", 5.0)
            >>> metrics.histogram("request.duration_ms", 123.45)
        """
        self._histograms[name].append(value)

    def gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """
        Set a gauge metric.

        Gauges represent point-in-time values.

        Args:
            name: Metric name (e.g., "queue.size")
            value: Current value
            tags: Optional tags for metric

        Example:
            >>> metrics.gauge("queue.size", 10)
            >>> metrics.gauge("memory.used_mb", 256.5)
        """
        self._gauges[name] = value

    @contextmanager
    def timer(self, name: str):
        """
        Context manager for timing operations.

        Automatically records duration as a histogram.

        Args:
            name: Metric name for duration

        Example:
            >>> with metrics.timer("donation.processing_time"):
            ...     process_donation()
        """
        start = time.time()
        try:
            yield
        finally:
            duration_ms = (time.time() - start) * 1000
            self.histogram(f"{name}.duration_ms", duration_ms)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics for all metrics.

        Returns:
            Dictionary with metric statistics

        Example:
            >>> stats = metrics.get_stats()
            >>> print(stats['counters']['donations.total'])
        """
        stats = {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {},
            "uptime_seconds": time.time() - self._start_time
        }

        # Calculate histogram statistics
        for name, values in self._histograms.items():
            if values:
                sorted_values = sorted(values)
                count = len(values)
                stats["histograms"][name] = {
                    "count": count,
                    "sum": sum(values),
                    "min": sorted_values[0],
                    "max": sorted_values[-1],
                    "mean": sum(values) / count,
                    "p50": sorted_values[int(count * 0.5)],
                    "p95": sorted_values[int(count * 0.95)] if count > 1 else sorted_values[0],
                    "p99": sorted_values[int(count * 0.99)] if count > 1 else sorted_values[0],
                }

        return stats

    def reset(self) -> None:
        """Reset all metrics."""
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()
        self._start_time = time.time()

    def export_json(self, file_path: Path) -> None:
        """
        Export metrics to JSON file.

        Args:
            file_path: Path to export file

        Example:
            >>> metrics.export_json(Path("metrics.json"))
        """
        stats = self.get_stats()
        stats["timestamp"] = datetime.now(timezone.utc).isoformat()

        with open(file_path, 'w') as f:
            json.dumps(stats, f, indent=2)


# Global metrics instance
metrics = MetricsCollector()


# ============================================================================ #
# OpenTelemetry Tracing                                                        #
# ============================================================================ #

class TracingManager:
    """
    Manager for OpenTelemetry distributed tracing.

    Provides optional tracing support with automatic fallback
    if OpenTelemetry is not installed.

    Example:
        >>> tracing = TracingManager(service_name="ddc")
        >>> with tracing.trace("donation.process") as span:
        ...     span.set_attribute("donor", "John")
        ...     process_donation()
    """

    def __init__(self, service_name: str = "ddc", enabled: bool = True):
        self.service_name = service_name
        self.enabled = enabled and OTEL_AVAILABLE
        self.tracer = None

        if self.enabled:
            self._setup_tracing()

    def _setup_tracing(self) -> None:
        """Setup OpenTelemetry tracing."""
        try:
            # Create resource with service name
            resource = Resource(attributes={
                "service.name": self.service_name
            })

            # Create tracer provider
            provider = TracerProvider(resource=resource)

            # Add console exporter (can be replaced with OTLP exporter for production)
            console_exporter = ConsoleSpanExporter()
            span_processor = BatchSpanProcessor(console_exporter)
            provider.add_span_processor(span_processor)

            # Set as global tracer provider
            trace.set_tracer_provider(provider)

            # Get tracer
            self.tracer = trace.get_tracer(__name__)

        except (RuntimeError) as e:
            print(f"Warning: Failed to setup OpenTelemetry tracing: {e}")
            self.enabled = False

    @contextmanager
    def trace(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """
        Create a tracing span.

        Args:
            name: Span name (e.g., "donation.process")
            attributes: Optional attributes to add to span

        Yields:
            Span object (or None if tracing disabled)

        Example:
            >>> with tracing.trace("donation.process", {"donor": "John"}) as span:
            ...     process_donation()
            ...     span.set_attribute("amount", 5.0)
        """
        if not self.enabled or not self.tracer:
            # No-op context manager if tracing disabled
            yield None
            return

        with self.tracer.start_as_current_span(name) as span:
            # Add attributes
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, value)

            try:
                yield span
            except (RuntimeError) as e:
                # Record exception in span
                span.set_status(Status(StatusCode.ERROR))
                span.record_exception(e)
                raise


# Global tracing instance (disabled by default)
tracing = TracingManager(enabled=False)


def enable_tracing(service_name: str = "ddc") -> None:
    """
    Enable OpenTelemetry tracing.

    Args:
        service_name: Service name for tracing

    Example:
        >>> enable_tracing("ddc")
    """
    global tracing
    tracing = TracingManager(service_name=service_name, enabled=True)


# ============================================================================ #
# Decorators                                                                   #
# ============================================================================ #

def traced(operation_name: Optional[str] = None):
    """
    Decorator to automatically trace a function.

    Args:
        operation_name: Optional name for the operation (defaults to function name)

    Example:
        >>> @traced("donation.process")
        ... def process_donation(donor: str, amount: float):
        ...     # Function is automatically traced
        ...     pass
    """
    def decorator(func):
        name = operation_name or f"{func.__module__}.{func.__name__}"

        def wrapper(*args, **kwargs):
            with tracing.trace(name) as span:
                # Add function arguments as attributes
                if span:
                    span.set_attribute("function", func.__name__)

                return func(*args, **kwargs)

        return wrapper
    return decorator


def timed(metric_name: Optional[str] = None):
    """
    Decorator to automatically time a function and record as metric.

    Args:
        metric_name: Optional metric name (defaults to function name)

    Example:
        >>> @timed("donation.processing_time")
        ... def process_donation():
        ...     # Function duration is automatically recorded
        ...     pass
    """
    def decorator(func):
        name = metric_name or f"{func.__module__}.{func.__name__}"

        def wrapper(*args, **kwargs):
            with metrics.timer(name):
                return func(*args, **kwargs)

        return wrapper
    return decorator


# ============================================================================ #
# Utility Functions                                                            #
# ============================================================================ #

def get_observability_context(
    logger_name: str,
    service_name: str = "ddc",
    use_json: bool = False
) -> Dict[str, Any]:
    """
    Get complete observability context (logger, metrics, tracing).

    Convenience function to get all observability tools at once.

    Args:
        logger_name: Logger name
        service_name: Service name
        use_json: Use JSON logging format

    Returns:
        Dictionary with logger, metrics, and tracing

    Example:
        >>> obs = get_observability_context(__name__, service_name="DonationService")
        >>> obs['logger'].info("Processing", extra={"amount": 5.0})
        >>> obs['metrics'].increment("donations.total")
        >>> with obs['tracing'].trace("process"):
        ...     pass
    """
    return {
        "logger": get_structured_logger(logger_name, service_name, use_json),
        "metrics": metrics,
        "tracing": tracing
    }
