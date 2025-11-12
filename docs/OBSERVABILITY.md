# DDC Observability Guide

Complete guide to monitoring, logging, metrics, and tracing in DockerDiscordControl.

## Table of Contents

- [Overview](#overview)
- [Structured Logging](#structured-logging)
- [Metrics Collection](#metrics-collection)
- [Distributed Tracing](#distributed-tracing)
- [Integration Examples](#integration-examples)
- [Exporting and Analysis](#exporting-and-analysis)
- [Best Practices](#best-practices)
- [Configuration](#configuration)

## Overview

DDC provides comprehensive observability through three pillars:

1. **Structured Logging**: JSON-formatted logs with rich context
2. **Metrics Collection**: Lightweight counters, histograms, and gauges
3. **Distributed Tracing**: OpenTelemetry integration for request tracing

### Design Principles

- **Lightweight**: Minimal overhead, optional features
- **No External Dependencies**: Works standalone without external services
- **Optional Integration**: OpenTelemetry is optional
- **Backward Compatible**: Works with existing logging code

```
┌─────────────────────────────────────┐
│         Application Code            │
│  - Services                         │
│  - Business Logic                   │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│      Observability Layer            │
│  - Structured Logger                │
│  - Metrics Collector                │
│  - Tracing Manager                  │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│          Output/Export              │
│  - Console (JSON/Text)              │
│  - Metrics JSON Files               │
│  - OpenTelemetry Exporters          │
└─────────────────────────────────────┘
```

## Structured Logging

### JSON Logging

Enable JSON-formatted logs for easy parsing by log aggregation systems.

**Basic Usage**:

```python
from utils.observability import get_structured_logger

logger = get_structured_logger(__name__, service_name="MyService", use_json=True)

# Log with structured context
logger.info("operation_completed", extra={
    "user_id": "12345",
    "duration_ms": 123.45,
    "items_processed": 10
})
```

**Output** (JSON format):

```json
{
  "timestamp": "2025-01-15T10:30:45.123Z",
  "level": "INFO",
  "logger": "ddc.my_service",
  "message": "operation_completed",
  "service": "MyService",
  "user_id": "12345",
  "duration_ms": 123.45,
  "items_processed": 10,
  "source": "my_service.py:42"
}
```

### Standard Text Logging

Continue using standard text logging (default behavior):

```python
from utils.observability import get_structured_logger

logger = get_structured_logger(__name__, service_name="MyService", use_json=False)

# Standard text format
logger.info("Processing donation", extra={"amount": 5.0})
```

**Output** (Text format):

```
2025-01-15 10:30:45 CET - ddc.my_service - INFO - Processing donation
```

### Logger with Default Context

Add default context to all log messages:

```python
from utils.observability import get_structured_logger

logger = get_structured_logger(
    __name__,
    service_name="DonationService",
    use_json=True,
    context={
        "service": "DonationService",
        "component": "processor",
        "version": "2.0"
    }
)

# Context is automatically added to all logs
logger.info("donation_processed", extra={"donor": "John", "amount": 5.0})
```

**Output**:

```json
{
  "timestamp": "2025-01-15T10:30:45.123Z",
  "level": "INFO",
  "message": "donation_processed",
  "service": "DonationService",
  "component": "processor",
  "version": "2.0",
  "donor": "John",
  "amount": 5.0
}
```

### Log Levels

Use appropriate log levels for different scenarios:

```python
# DEBUG: Detailed diagnostic information
logger.debug("cache_hit", extra={"key": "config", "ttl": 300})

# INFO: Informational messages about normal operations
logger.info("donation_processed", extra={"amount": 5.0})

# WARNING: Warning messages for potentially problematic situations
logger.warning("retry_attempt", extra={"attempt": 2, "max_attempts": 3})

# ERROR: Error messages for failures
logger.error("api_call_failed", extra={"error": str(exc), "url": url})

# CRITICAL: Critical errors requiring immediate attention
logger.critical("service_unavailable", extra={"service": "docker"})
```

## Metrics Collection

### Overview

DDC provides a lightweight metrics collector for tracking operations.

**Metric Types**:

- **Counters**: Incrementing values (e.g., total donations, errors)
- **Histograms**: Distribution of values (e.g., donation amounts, latencies)
- **Gauges**: Point-in-time values (e.g., queue size, memory usage)

### Using Metrics

```python
from utils.observability import metrics

# Counters: Track events
metrics.increment("donations.total")
metrics.increment("api.requests", value=1, tags={"endpoint": "/donate"})
metrics.decrement("queue.size")

# Histograms: Track distributions
metrics.histogram("donation.amount", 5.0)
metrics.histogram("request.duration_ms", 123.45)

# Gauges: Track current values
metrics.gauge("queue.size", 10)
metrics.gauge("memory.used_mb", 256.5)

# Timing operations
with metrics.timer("donation.processing_time"):
    process_donation()
    # Duration automatically recorded as "donation.processing_time.duration_ms"
```

### Metrics in Services

**Example: DonationService with Metrics**:

```python
from utils.observability import metrics
import time

def process_donation(donor_name: str, amount: float):
    start_time = time.time()

    # Track attempt
    metrics.increment("donations.attempts.total")

    try:
        # Process donation
        result = execute_donation(donor_name, amount)

        # Track success
        metrics.increment("donations.total")
        metrics.histogram("donation.amount", amount)

        # Track duration
        duration_ms = (time.time() - start_time) * 1000
        metrics.histogram("donation.processing_time.duration_ms", duration_ms)

        return result

    except Exception as exc:
        # Track failure
        metrics.increment("donations.failed.total")
        raise
```

### Getting Metrics Statistics

```python
from utils.observability import metrics

# Get all statistics
stats = metrics.get_stats()

print(f"Total donations: {stats['counters']['donations.total']}")
print(f"Average amount: {stats['histograms']['donation.amount']['mean']}")
print(f"P95 latency: {stats['histograms']['donation.processing_time.duration_ms']['p95']}ms")
```

**Example Output**:

```python
{
    "counters": {
        "donations.total": 150,
        "donations.failed.total": 2
    },
    "gauges": {
        "queue.size": 10
    },
    "histograms": {
        "donation.amount": {
            "count": 150,
            "sum": 750.0,
            "min": 1.0,
            "max": 50.0,
            "mean": 5.0,
            "p50": 5.0,
            "p95": 10.0,
            "p99": 20.0
        }
    },
    "uptime_seconds": 3600.0
}
```

### Exporting Metrics

```python
from utils.observability import metrics
from pathlib import Path

# Export to JSON file
metrics.export_json(Path("metrics/current_metrics.json"))

# Reset metrics
metrics.reset()
```

## Distributed Tracing

### Overview

DDC supports OpenTelemetry distributed tracing (optional).

**Features**:

- Trace request flows across services
- Measure operation latencies
- Debug complex interactions
- Optional: Works without tracing enabled

### Enabling Tracing

```python
from utils.observability import enable_tracing

# Enable tracing for the service
enable_tracing(service_name="ddc")
```

### Using Tracing

**Context Manager**:

```python
from utils.observability import tracing

# Create a trace span
with tracing.trace("donation.process", attributes={
    "donor": "John",
    "source": "web_ui"
}) as span:
    # Your code here
    process_donation()

    # Add more attributes
    if span:
        span.set_attribute("amount", 5.0)
        span.set_attribute("success", True)
```

**Decorator**:

```python
from utils.observability import traced

@traced("donation.process")
def process_donation(donor: str, amount: float):
    # Function is automatically traced
    # Arguments are added as attributes
    pass

# Usage
process_donation("John", 5.0)
```

### Tracing with Error Handling

```python
from utils.observability import tracing

with tracing.trace("api.call") as span:
    try:
        response = make_api_call()

        if span:
            span.set_attribute("status_code", response.status_code)
            span.set_attribute("success", True)

    except Exception as exc:
        # Exception is automatically recorded in span
        if span:
            span.set_attribute("success", False)
        raise
```

### Trace Exporters

By default, traces are output to console. Configure exporters for production:

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Export to OTLP endpoint (e.g., Jaeger, Tempo)
otlp_exporter = OTLPSpanExporter(
    endpoint="http://localhost:4317",
    insecure=True
)

# Add to tracer provider (in observability.py setup)
```

## Integration Examples

### Complete Service Example

**services/my_service.py**:

```python
from utils.observability import get_structured_logger, metrics, tracing
import time

# Setup structured logger
logger = get_structured_logger(
    __name__,
    service_name="MyService",
    use_json=False,  # Use True for JSON output
    context={
        "service": "MyService",
        "version": "2.0"
    }
)

class MyService:
    def process_request(self, request_id: str, data: dict) -> dict:
        """Process a request with full observability."""
        start_time = time.time()

        # Metrics: Track attempt
        metrics.increment("requests.attempts.total", tags={"service": "MyService"})

        # Tracing: Create span
        with tracing.trace("request.process", attributes={
            "request_id": request_id,
            "service": "MyService"
        }) as span:
            try:
                # Log start
                logger.info("request_started", extra={
                    "request_id": request_id,
                    "data_size": len(data)
                })

                # Process request
                result = self._execute_processing(data)

                # Calculate duration
                duration_ms = (time.time() - start_time) * 1000

                # Metrics: Track success
                metrics.increment("requests.total", tags={"service": "MyService"})
                metrics.histogram("request.processing_time.duration_ms", duration_ms)

                # Log success
                logger.info("request_completed", extra={
                    "request_id": request_id,
                    "result_size": len(result),
                    "duration_ms": duration_ms,
                    "success": True
                })

                # Tracing: Add success attributes
                if span:
                    span.set_attribute("success", True)
                    span.set_attribute("duration_ms", duration_ms)
                    span.set_attribute("result_size", len(result))

                return result

            except Exception as exc:
                duration_ms = (time.time() - start_time) * 1000

                # Metrics: Track failure
                metrics.increment("requests.failed.total", tags={"service": "MyService"})

                # Log error
                logger.error("request_failed", extra={
                    "request_id": request_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                    "success": False
                })

                # Tracing: Mark as failed (automatic exception recording)
                if span:
                    span.set_attribute("success", False)
                    span.set_attribute("error_type", type(exc).__name__)

                raise

    def _execute_processing(self, data: dict) -> dict:
        # Your business logic here
        return {"processed": True}
```

### Real Example: UnifiedDonationService

See `services/donation/unified/service.py` for a complete real-world example.

**Key Features**:

- Structured logging with rich context
- Metrics tracking (attempts, successes, failures, amounts, durations)
- OpenTelemetry tracing spans
- Error handling with observability
- Both sync and async support

## Exporting and Analysis

### Metrics Export

**Export to JSON**:

```python
from utils.observability import metrics
from pathlib import Path

# Export current metrics
metrics.export_json(Path("metrics/metrics_2025-01-15.json"))
```

**Automated Export** (e.g., cronjob):

```bash
#!/bin/bash
# export_metrics.sh

python3 -c "
from utils.observability import metrics
from pathlib import Path
from datetime import datetime

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
metrics.export_json(Path(f'metrics/metrics_{timestamp}.json'))
print(f'Metrics exported to metrics/metrics_{timestamp}.json')
"
```

### Log Analysis

**JSON Logs with jq**:

```bash
# Filter error logs
cat logs/ddc.log | jq 'select(.level == "ERROR")'

# Get donation amounts
cat logs/ddc.log | jq 'select(.message == "donation_processed") | .amount'

# Calculate average duration
cat logs/ddc.log | jq 'select(.duration_ms) | .duration_ms' | awk '{sum+=$1; n++} END {print sum/n}'

# Top donors
cat logs/ddc.log | jq 'select(.message == "donation_processed") | .donor' | sort | uniq -c | sort -nr | head -10
```

### Metrics Dashboard

**Simple Python Dashboard**:

```python
from utils.observability import metrics
from datetime import datetime

def print_metrics_dashboard():
    stats = metrics.get_stats()

    print("=" * 60)
    print(f"DDC Metrics Dashboard - {datetime.now()}")
    print("=" * 60)

    # Counters
    print("\nCOUNTERS:")
    for name, value in stats['counters'].items():
        print(f"  {name}: {value}")

    # Gauges
    print("\nGAUGES:")
    for name, value in stats['gauges'].items():
        print(f"  {name}: {value}")

    # Histograms
    print("\nHISTOGRAMS:")
    for name, hist in stats['histograms'].items():
        print(f"  {name}:")
        print(f"    Count: {hist['count']}")
        print(f"    Mean: {hist['mean']:.2f}")
        print(f"    P50: {hist['p50']:.2f}")
        print(f"    P95: {hist['p95']:.2f}")
        print(f"    P99: {hist['p99']:.2f}")

    print(f"\nUptime: {stats['uptime_seconds']:.0f} seconds")
    print("=" * 60)

# Run dashboard
print_metrics_dashboard()
```

## Best Practices

### Logging Best Practices

**1. Use Descriptive Event Names**:

```python
# ✅ Good: Clear event name
logger.info("donation_processed", extra={"amount": 5.0})

# ❌ Bad: Vague message
logger.info("Processing completed")
```

**2. Include Relevant Context**:

```python
# ✅ Good: Rich context
logger.info("api_call_completed", extra={
    "endpoint": "/api/donate",
    "method": "POST",
    "status_code": 200,
    "duration_ms": 123.45,
    "user_id": "12345"
})

# ❌ Bad: Missing context
logger.info("API call done")
```

**3. Use Appropriate Log Levels**:

```python
# DEBUG: Verbose diagnostic info (disabled in production)
logger.debug("cache_lookup", extra={"key": "config"})

# INFO: Normal operations
logger.info("donation_processed", extra={"amount": 5.0})

# WARNING: Potential issues
logger.warning("retry_attempt", extra={"attempt": 2})

# ERROR: Errors that need attention
logger.error("payment_failed", extra={"error": str(exc)})

# CRITICAL: Critical failures
logger.critical("database_unavailable", extra={"error": str(exc)})
```

**4. Don't Log Sensitive Data**:

```python
# ✅ Good: Masked sensitive data
logger.info("payment_processed", extra={
    "card_last4": "1234",
    "amount": 5.0
})

# ❌ Bad: Logging sensitive data
logger.info("payment", extra={
    "card_number": "4111111111111111"  # NEVER DO THIS
})
```

### Metrics Best Practices

**1. Use Consistent Naming**:

```python
# Use dot notation: category.subcategory.metric
metrics.increment("donations.total")
metrics.increment("donations.failed.total")
metrics.histogram("donation.amount")
metrics.histogram("donation.processing_time.duration_ms")
```

**2. Track Both Success and Failure**:

```python
metrics.increment("operations.attempts.total")

try:
    execute_operation()
    metrics.increment("operations.total")  # Success
except Exception:
    metrics.increment("operations.failed.total")  # Failure
    raise
```

**3. Measure Durations**:

```python
# Use timer context manager
with metrics.timer("operation.duration"):
    execute_operation()

# Or manual timing
start = time.time()
execute_operation()
duration_ms = (time.time() - start) * 1000
metrics.histogram("operation.duration_ms", duration_ms)
```

**4. Track Business Metrics**:

```python
# Not just technical metrics, but business metrics too
metrics.histogram("donation.amount", amount)
metrics.increment("users.active.total")
metrics.gauge("queue.waiting.count", pending_count)
```

### Tracing Best Practices

**1. Create Meaningful Spans**:

```python
# ✅ Good: Descriptive span names
with tracing.trace("donation.process"):
    process_donation()

with tracing.trace("database.query.select"):
    query_database()

# ❌ Bad: Generic names
with tracing.trace("operation"):
    do_something()
```

**2. Add Relevant Attributes**:

```python
with tracing.trace("api.call", attributes={
    "http.method": "POST",
    "http.url": "/api/donate",
    "http.status_code": 200
}) as span:
    response = make_api_call()

    if span:
        span.set_attribute("response.size", len(response))
```

**3. Nest Spans for Complex Operations**:

```python
with tracing.trace("donation.process") as parent_span:
    # Parent span for entire operation

    with tracing.trace("donation.validate"):
        validate_donation()

    with tracing.trace("donation.execute"):
        execute_donation()

    with tracing.trace("donation.notify"):
        send_notifications()
```

## Configuration

### Environment Variables

```bash
# Enable JSON logging
export DDC_JSON_LOGS=true

# Enable OpenTelemetry tracing
export DDC_OTEL_ENABLED=true
export DDC_OTEL_SERVICE_NAME=ddc
export DDC_OTEL_ENDPOINT=http://localhost:4317
```

### Programmatic Configuration

```python
from utils.observability import enable_tracing, get_structured_logger
import os

# Enable tracing if configured
if os.getenv("DDC_OTEL_ENABLED", "false").lower() == "true":
    enable_tracing(service_name=os.getenv("DDC_OTEL_SERVICE_NAME", "ddc"))

# Configure JSON logging
use_json = os.getenv("DDC_JSON_LOGS", "false").lower() == "true"
logger = get_structured_logger(__name__, use_json=use_json)
```

## Integration with External Systems

### Prometheus (Future)

For production environments, metrics can be exposed via Prometheus endpoint:

```python
# Future integration example
from prometheus_client import Counter, Histogram, Gauge

# Convert DDC metrics to Prometheus metrics
donation_counter = Counter('ddc_donations_total', 'Total donations')
donation_amount = Histogram('ddc_donation_amount', 'Donation amounts')
```

### Grafana Loki (JSON Logs)

DDC JSON logs can be ingested by Grafana Loki for visualization:

```yaml
# promtail config example
scrape_configs:
  - job_name: ddc
    static_configs:
      - targets:
          - localhost
        labels:
          job: ddc
          __path__: /var/log/ddc/*.log
    pipeline_stages:
      - json:
          expressions:
            level: level
            service: service
            message: message
```

### Jaeger (Tracing)

Export traces to Jaeger for visualization:

```python
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

jaeger_exporter = JaegerExporter(
    agent_host_name="localhost",
    agent_port=6831,
)
```

## Troubleshooting

### No Metrics Recorded

**Problem**: Metrics not showing up

**Solution**:

```python
from utils.observability import metrics

# Check if metrics are being recorded
stats = metrics.get_stats()
print(f"Counters: {stats['counters']}")

# Ensure you're using global metrics instance
from utils.observability import metrics
metrics.increment("test")  # Use global instance, not a new one
```

### Tracing Not Working

**Problem**: Tracing spans not appearing

**Solution**:

```python
# 1. Check if OpenTelemetry is installed
try:
    import opentelemetry
    print("OpenTelemetry installed")
except ImportError:
    print("Install OpenTelemetry: pip install opentelemetry-api opentelemetry-sdk")

# 2. Enable tracing
from utils.observability import enable_tracing
enable_tracing(service_name="ddc")

# 3. Check if tracing is enabled
from utils.observability import tracing
print(f"Tracing enabled: {tracing.enabled}")
```

### JSON Logging Not Formatted

**Problem**: Logs are not in JSON format

**Solution**:

```python
# Ensure use_json=True
from utils.observability import get_structured_logger

logger = get_structured_logger(__name__, use_json=True)  # Must be True
logger.info("test", extra={"key": "value"})
```

## See Also

- [PERFORMANCE.md](PERFORMANCE.md) - Performance testing and metrics
- [CODE_QUALITY.md](CODE_QUALITY.md) - Code quality standards
- [SERVICES.md](SERVICES.md) - Service architecture
- [ERROR_HANDLING.md](ERROR_HANDLING.md) - Exception handling

## External Resources

- **OpenTelemetry**: https://opentelemetry.io/
- **Grafana Loki**: https://grafana.com/oss/loki/
- **Prometheus**: https://prometheus.io/
- **Jaeger**: https://www.jaegertracing.io/
