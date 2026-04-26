# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Unit Tests for utils/* metrics & observability #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Functional unit tests covering:

- utils/performance_metrics.py  (Counter, Timer, Stats aggregation)
- utils/observability.py        (Logger setup, MetricsCollector, decorators)
- utils/time_utils.py           (Datetime parsing, timezone, format helpers)
- utils/common_helpers.py       (validate_container_name and pure helpers)

Designed to exercise as many uncovered branches as possible without touching
production code.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from utils import common_helpers as ch
from utils import time_utils as tu
from utils import observability as obs
from utils import performance_metrics as pm


# =========================================================================== #
# performance_metrics.py                                                      #
# =========================================================================== #

@pytest.fixture
def metrics_instance(tmp_path, monkeypatch):
    """Yield a PerformanceMetrics singleton bound to a temp metrics file."""
    # Reset singleton state so __init__ runs again
    pm.PerformanceMetrics._instance = None
    instance = pm.PerformanceMetrics()
    instance.metrics_dir = tmp_path
    instance.metrics_file = tmp_path / "performance_metrics.jsonl"
    instance.current_operations = {}
    yield instance
    pm.PerformanceMetrics._instance = None


def test_metric_entry_to_dict_roundtrip():
    entry = pm.MetricEntry(
        operation="op1",
        start_time=1.0,
        end_time=2.5,
        duration=1.5,
        success=True,
        timestamp="2025-01-01T00:00:00",
        metadata={"k": "v"},
    )
    d = entry.to_dict()
    assert d["operation"] == "op1"
    assert d["duration"] == 1.5
    assert d["metadata"] == {"k": "v"}


def test_metric_stats_to_dict():
    stats = pm.MetricStats(
        operation="op",
        total_calls=1,
        successful_calls=1,
        failed_calls=0,
        min_duration=0.1,
        max_duration=0.1,
        avg_duration=0.1,
        p50_duration=0.1,
        p95_duration=0.1,
        p99_duration=0.1,
        last_24h_calls=1,
        last_hour_calls=1,
    )
    d = stats.to_dict()
    assert d["operation"] == "op"
    assert d["total_calls"] == 1


def test_performance_metrics_singleton(metrics_instance):
    a = pm.PerformanceMetrics()
    b = pm.PerformanceMetrics()
    assert a is b


def test_get_performance_metrics_returns_singleton(metrics_instance):
    pm._metrics_instance = None
    inst = pm.get_performance_metrics()
    inst2 = pm.get_performance_metrics()
    assert inst is inst2


def test_start_and_end_writes_metric(metrics_instance):
    metrics_instance.start("docker_op")
    duration = metrics_instance.end("docker_op", success=True, metadata={"container": "nginx"})
    assert duration >= 0
    assert metrics_instance.metrics_file.exists()
    line = metrics_instance.metrics_file.read_text().strip()
    data = json.loads(line)
    assert data["operation"] == "docker_op"
    assert data["success"] is True
    assert data["metadata"] == {"container": "nginx"}


def test_end_unstarted_operation_returns_zero(metrics_instance):
    duration = metrics_instance.end("never_started")
    assert duration == 0.0


def test_track_context_manager_success(metrics_instance):
    with metrics_instance.track("ctx_op"):
        pass
    line = metrics_instance.metrics_file.read_text().strip()
    data = json.loads(line)
    assert data["operation"] == "ctx_op"
    assert data["success"] is True


def test_track_context_manager_handles_exception(metrics_instance):
    with pytest.raises(ValueError):
        with metrics_instance.track("err_op", metadata={"foo": "bar"}):
            raise ValueError("boom")
    line = metrics_instance.metrics_file.read_text().strip()
    data = json.loads(line)
    assert data["success"] is False
    assert "error" in data["metadata"]
    assert data["metadata"]["foo"] == "bar"


def test_get_stats_empty_when_no_file(metrics_instance):
    assert metrics_instance.get_stats() == {}


def test_get_stats_aggregates_entries(metrics_instance):
    # Write multiple entries directly
    now = time.time()
    entries = []
    for i, dur in enumerate([0.1, 0.2, 0.3, 0.4, 0.5]):
        entries.append({
            "operation": "agg_op",
            "start_time": now - dur,
            "end_time": now - (i * 0.001),
            "duration": dur,
            "success": i != 4,  # last one is failure
            "timestamp": datetime.now().isoformat(),
            "metadata": {},
        })
    with open(metrics_instance.metrics_file, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    stats = metrics_instance.get_stats()
    assert "agg_op" in stats
    s = stats["agg_op"]
    assert s.total_calls == 5
    assert s.successful_calls == 4
    assert s.failed_calls == 1
    assert s.min_duration == 0.1
    assert s.max_duration == 0.5
    assert pytest.approx(s.avg_duration, rel=1e-6) == 0.3
    assert s.last_hour_calls == 5


def test_get_stats_filters_by_operation(metrics_instance):
    now = time.time()
    with open(metrics_instance.metrics_file, "w") as f:
        for op in ["op_a", "op_b"]:
            f.write(json.dumps({
                "operation": op, "start_time": now - 0.1, "end_time": now,
                "duration": 0.1, "success": True,
                "timestamp": "x", "metadata": {},
            }) + "\n")
    stats = metrics_instance.get_stats(operation="op_a")
    assert list(stats.keys()) == ["op_a"]


def test_get_stats_skips_old_entries(metrics_instance):
    now = time.time()
    with open(metrics_instance.metrics_file, "w") as f:
        f.write(json.dumps({
            "operation": "old", "start_time": 0, "end_time": now - 99999999,
            "duration": 0.1, "success": True, "timestamp": "x", "metadata": {},
        }) + "\n")
    stats = metrics_instance.get_stats(last_hours=1)
    assert stats == {}


def test_get_stats_skips_malformed_lines(metrics_instance):
    now = time.time()
    with open(metrics_instance.metrics_file, "w") as f:
        f.write("not-json\n")
        f.write(json.dumps({
            "operation": "valid", "start_time": now, "end_time": now,
            "duration": 0.1, "success": True, "timestamp": "x", "metadata": {},
        }) + "\n")
    stats = metrics_instance.get_stats()
    assert "valid" in stats


def test_get_recent_metrics_empty_when_no_file(metrics_instance):
    assert metrics_instance.get_recent_metrics() == []


def test_get_recent_metrics_returns_entries(metrics_instance):
    now = time.time()
    with open(metrics_instance.metrics_file, "w") as f:
        for op in ["a", "b", "c"]:
            f.write(json.dumps({
                "operation": op, "start_time": now, "end_time": now,
                "duration": 0.1, "success": True, "timestamp": "x", "metadata": {},
            }) + "\n")
    entries = metrics_instance.get_recent_metrics(limit=10)
    assert len(entries) == 3
    # Filter by op
    only_b = metrics_instance.get_recent_metrics(operation="b", limit=10)
    assert len(only_b) == 1
    assert only_b[0].operation == "b"


def test_cleanup_old_metrics_removes_expired(metrics_instance):
    now = time.time()
    with open(metrics_instance.metrics_file, "w") as f:
        # One old, one fresh
        f.write(json.dumps({
            "operation": "old", "start_time": 0, "end_time": now - (100 * 86400),
            "duration": 0.1, "success": True, "timestamp": "x", "metadata": {},
        }) + "\n")
        f.write(json.dumps({
            "operation": "fresh", "start_time": now, "end_time": now,
            "duration": 0.1, "success": True, "timestamp": "x", "metadata": {},
        }) + "\n")
    removed = metrics_instance.cleanup_old_metrics(days=30)
    assert removed == 1
    remaining = metrics_instance.metrics_file.read_text().strip().splitlines()
    assert len(remaining) == 1
    assert "fresh" in remaining[0]


def test_cleanup_old_metrics_no_file_returns_zero(metrics_instance):
    if metrics_instance.metrics_file.exists():
        metrics_instance.metrics_file.unlink()
    assert metrics_instance.cleanup_old_metrics(days=30) == 0


def test_export_to_json_writes_stats(metrics_instance, tmp_path):
    now = time.time()
    with open(metrics_instance.metrics_file, "w") as f:
        f.write(json.dumps({
            "operation": "exp_op", "start_time": now, "end_time": now,
            "duration": 0.42, "success": True, "timestamp": "x", "metadata": {},
        }) + "\n")
    out = tmp_path / "exported.json"
    assert metrics_instance.export_to_json(out) is True
    payload = json.loads(out.read_text())
    assert "statistics" in payload
    assert "exp_op" in payload["statistics"]


def test_calculate_stats_empty_returns_zeros(metrics_instance):
    s = metrics_instance._calculate_stats("nothing", [])
    assert s.total_calls == 0
    assert s.min_duration == 0.0
    assert s.p99_duration == 0.0


# =========================================================================== #
# observability.py                                                            #
# =========================================================================== #

def test_json_formatter_basic_format():
    formatter = obs.JSONFormatter(service_name="svc-x")
    record = logging.LogRecord(
        name="ddc.test", level=logging.INFO, pathname="x.py",
        lineno=10, msg="hello", args=(), exc_info=None,
    )
    out = formatter.format(record)
    payload = json.loads(out)
    assert payload["level"] == "INFO"
    assert payload["service"] == "svc-x"
    assert payload["message"] == "hello"
    assert payload["logger"] == "ddc.test"
    assert "timestamp" in payload
    assert payload["source"].endswith(":10")


def test_json_formatter_includes_extra_fields():
    formatter = obs.JSONFormatter()
    record = logging.LogRecord(
        name="ddc.test", level=logging.INFO, pathname="x.py",
        lineno=1, msg="m", args=(), exc_info=None,
    )
    record.donor = "John"
    record.amount = 5.0
    payload = json.loads(formatter.format(record))
    assert payload["donor"] == "John"
    assert payload["amount"] == 5.0


def test_json_formatter_includes_exception_info():
    formatter = obs.JSONFormatter()
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        import sys
        record = logging.LogRecord(
            name="ddc.test", level=logging.ERROR, pathname="x.py",
            lineno=1, msg="failed", args=(), exc_info=sys.exc_info(),
        )
    payload = json.loads(formatter.format(record))
    assert "exception" in payload
    assert "RuntimeError" in payload["exception"]


def test_structured_logger_merges_context(caplog):
    base_logger = logging.getLogger("ddc.struct.test")
    sl = obs.StructuredLogger(base_logger, {"service": "Svc"})
    msg, kwargs = sl.process("hello", {})
    assert kwargs["extra"]["service"] == "Svc"


def test_get_structured_logger_returns_adapter():
    logger = obs.get_structured_logger("ddc.tests.unique1", use_json=True, context={"a": 1})
    assert isinstance(logger, obs.StructuredLogger)
    # Calling again should not duplicate handlers
    obs.get_structured_logger("ddc.tests.unique1", use_json=True)
    base = logging.getLogger("ddc.tests.unique1")
    assert len(base.handlers) == 1


def test_metrics_collector_counters_and_decrement():
    mc = obs.MetricsCollector()
    mc.increment("a")
    mc.increment("a", value=4)
    mc.decrement("a", value=2)
    stats = mc.get_stats()
    assert stats["counters"]["a"] == 3


def test_metrics_collector_gauge_overwrites():
    mc = obs.MetricsCollector()
    mc.gauge("g", 10)
    mc.gauge("g", 42)
    assert mc.get_stats()["gauges"]["g"] == 42


def test_metrics_collector_histogram_stats():
    mc = obs.MetricsCollector()
    for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
        mc.histogram("dur", v)
    h = mc.get_stats()["histograms"]["dur"]
    assert h["count"] == 5
    assert h["min"] == 1.0
    assert h["max"] == 5.0
    assert h["mean"] == 3.0
    assert h["p50"] == 3.0
    assert h["sum"] == 15.0


def test_metrics_collector_timer_records_duration():
    mc = obs.MetricsCollector()
    with mc.timer("op"):
        time.sleep(0.001)
    h = mc.get_stats()["histograms"]["op.duration_ms"]
    assert h["count"] == 1
    assert h["min"] >= 0


def test_metrics_collector_reset_clears_state():
    mc = obs.MetricsCollector()
    mc.increment("k")
    mc.gauge("g", 5)
    mc.histogram("h", 1.0)
    mc.reset()
    stats = mc.get_stats()
    assert stats["counters"] == {}
    assert stats["gauges"] == {}
    assert stats["histograms"] == {}


def test_metrics_collector_get_stats_uptime_positive():
    mc = obs.MetricsCollector()
    time.sleep(0.001)
    assert mc.get_stats()["uptime_seconds"] > 0


def test_traced_decorator_passes_through_when_disabled():
    @obs.traced("custom.op")
    def my_func(x, y):
        return x + y

    # Default tracing instance is disabled, should still call function
    assert my_func(2, 3) == 5


def test_timed_decorator_records_metric():
    obs.metrics.reset()

    @obs.timed("my.metric")
    def slow_func():
        time.sleep(0.001)
        return "ok"

    assert slow_func() == "ok"
    stats = obs.metrics.get_stats()
    assert "my.metric.duration_ms" in stats["histograms"]


def test_get_observability_context_returns_all_keys():
    ctx = obs.get_observability_context("ddc.tests.ctx", service_name="svc")
    assert "logger" in ctx
    assert "metrics" in ctx
    assert "tracing" in ctx
    assert isinstance(ctx["logger"], obs.StructuredLogger)


def test_tracing_manager_disabled_yields_none():
    tm = obs.TracingManager(enabled=False)
    with tm.trace("op", {"a": 1}) as span:
        assert span is None


# =========================================================================== #
# time_utils.py                                                               #
# =========================================================================== #

def test_get_datetime_imports_returns_tuple():
    dt, td, tz, t = tu.get_datetime_imports()
    assert dt is datetime
    assert td is timedelta
    assert tz is timezone
    # 'time' is the time module; verify it has .time()
    assert callable(t.time)


def test_get_current_time_utc_default():
    dt = tu.get_current_time()
    assert dt.tzinfo is not None


def test_get_current_time_with_valid_tz():
    dt = tu.get_current_time("Europe/Berlin")
    assert dt.tzinfo is not None


def test_get_current_time_with_invalid_tz_falls_back_utc():
    dt = tu.get_current_time("Not/A_Zone")
    assert dt.tzinfo == timezone.utc


def test_get_utc_timestamp_is_float():
    ts = tu.get_utc_timestamp()
    assert isinstance(ts, float)
    assert ts > 0


def test_timestamp_to_datetime_default_utc():
    dt = tu.timestamp_to_datetime(1700000000.0)
    assert dt.tzinfo == timezone.utc


def test_timestamp_to_datetime_with_tz():
    dt = tu.timestamp_to_datetime(1700000000.0, "Europe/Berlin")
    assert dt.tzinfo is not None
    # Same instant, just rendered in another tz
    assert dt.timestamp() == pytest.approx(1700000000.0)


def test_timestamp_to_datetime_invalid_tz_returns_utc():
    dt = tu.timestamp_to_datetime(1700000000.0, "Bogus/Zone")
    assert dt.tzinfo == timezone.utc


def test_datetime_to_timestamp_naive_treated_as_utc():
    naive = datetime(2024, 1, 1, 0, 0, 0)
    ts = tu.datetime_to_timestamp(naive)
    aware = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert ts == aware.timestamp()


def test_datetime_to_timestamp_aware():
    aware = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert tu.datetime_to_timestamp(aware) == aware.timestamp()


def test_format_duration_seconds():
    assert tu.format_duration(15) == "15.0s"


def test_format_duration_minutes():
    assert tu.format_duration(125) == "2m 5s"


def test_format_duration_hours():
    assert tu.format_duration(3725) == "1h 2m"


def test_format_duration_days():
    assert tu.format_duration(86400 * 2 + 3600 * 5) == "2d 5h"


def test_is_same_day_same_utc():
    a = datetime(2024, 6, 15, 1, 0, 0, tzinfo=timezone.utc)
    b = datetime(2024, 6, 15, 23, 0, 0, tzinfo=timezone.utc)
    assert tu.is_same_day(a, b) is True


def test_is_same_day_different_dates():
    a = datetime(2024, 6, 15, tzinfo=timezone.utc)
    b = datetime(2024, 6, 16, tzinfo=timezone.utc)
    assert tu.is_same_day(a, b) is False


def test_is_same_day_with_invalid_tz():
    a = datetime(2024, 6, 15, tzinfo=timezone.utc)
    b = datetime(2024, 6, 15, tzinfo=timezone.utc)
    assert tu.is_same_day(a, b, tz_name="Invalid/Zone") is True


def test_get_timezone_offset_known():
    offset = tu.get_timezone_offset("UTC")
    assert offset == "+0000"


def test_get_timezone_offset_unknown_returns_default():
    assert tu.get_timezone_offset("Bogus/Zone") == "+00:00"


def test_format_datetime_with_timezone_with_datetime():
    dt = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    result = tu.format_datetime_with_timezone(dt, timezone_name="UTC")
    assert "2024" in result and "12:00:00" in result


def test_format_datetime_with_timezone_time_only():
    dt = datetime(2024, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
    result = tu.format_datetime_with_timezone(dt, timezone_name="UTC", time_only=True)
    assert result == "12:30:45"


def test_format_datetime_with_timezone_from_timestamp():
    result = tu.format_datetime_with_timezone(1700000000, timezone_name="UTC")
    assert "2023" in result or "2024" in result  # safe range


def test_format_datetime_with_timezone_invalid_value():
    result = tu.format_datetime_with_timezone("not-a-date", timezone_name="UTC")
    assert "Time not available" in result or "error" in result.lower()


def test_format_datetime_with_timezone_naive_dt():
    dt = datetime(2024, 1, 1, 0, 0, 0)
    out = tu.format_datetime_with_timezone(dt, timezone_name="UTC")
    assert "2024" in out


def test_parse_timestamp_iso_with_microseconds():
    dt = tu.parse_timestamp("2024-01-15T10:30:45.123456Z")
    assert dt is not None
    assert dt.year == 2024 and dt.month == 1 and dt.day == 15


def test_parse_timestamp_iso_z():
    dt = tu.parse_timestamp("2024-01-15T10:30:45Z")
    assert dt is not None


def test_parse_timestamp_python_default():
    dt = tu.parse_timestamp("2024-01-15 10:30:45")
    assert dt is not None
    assert dt.tzinfo is not None  # Defaults to UTC


def test_parse_timestamp_just_date():
    dt = tu.parse_timestamp("2024-01-15")
    assert dt is not None


def test_parse_timestamp_invalid_returns_none():
    assert tu.parse_timestamp("not a real timestamp") is None


def test_clear_timezone_cache_resets():
    tu._cached_timezone = "Europe/Berlin"
    tu._cache_timestamp = time.time()
    tu.clear_timezone_cache()
    assert tu._cached_timezone is None
    assert tu._cache_timestamp is None


def test_get_configured_timezone_uses_env(monkeypatch):
    tu.clear_timezone_cache()
    monkeypatch.setenv("TZ", "Europe/Berlin")
    assert tu.get_configured_timezone() == "Europe/Berlin"
    tu.clear_timezone_cache()


def test_get_configured_timezone_caches(monkeypatch):
    tu.clear_timezone_cache()
    monkeypatch.setenv("TZ", "UTC")
    first = tu.get_configured_timezone()
    # Even if env changes, cached value is returned
    monkeypatch.setenv("TZ", "Europe/Berlin")
    second = tu.get_configured_timezone()
    assert first == second
    tu.clear_timezone_cache()


def test_get_log_timestamp_includes_tz(monkeypatch):
    tu.clear_timezone_cache()
    monkeypatch.setenv("TZ", "UTC")
    ts = tu.get_log_timestamp(include_tz=True)
    assert "UTC" in ts
    tu.clear_timezone_cache()


def test_get_log_timestamp_without_tz(monkeypatch):
    tu.clear_timezone_cache()
    monkeypatch.setenv("TZ", "UTC")
    ts = tu.get_log_timestamp(include_tz=False)
    assert "UTC" not in ts
    tu.clear_timezone_cache()


def test__get_timezone_safe_no_env_no_config(monkeypatch):
    """Without TZ env and with config service raising, returns 'UTC' default."""
    monkeypatch.delenv("TZ", raising=False)
    tu.clear_timezone_cache()
    # Stub config_service to fail import / lookup so we hit the fallback path.
    # Use sys.modules monkeypatching to make 'services.config.config_service'
    # raise ImportError-like behavior.
    import sys
    fake_module = type(sys)("services.config.config_service")

    def _broken_load_config():
        raise RuntimeError("nope")

    def _broken_get_config_service():
        raise RuntimeError("nope")

    fake_module.load_config = _broken_load_config
    fake_module.get_config_service = _broken_get_config_service
    monkeypatch.setitem(sys.modules, "services.config.config_service", fake_module)

    tz = tu._get_timezone_safe()
    assert tz == "UTC"
    tu.clear_timezone_cache()


def test__get_timezone_safe_returns_config_value(monkeypatch):
    """Returns timezone from load_config when TZ env not set."""
    monkeypatch.delenv("TZ", raising=False)
    tu.clear_timezone_cache()
    import sys
    fake_module = type(sys)("services.config.config_service")
    fake_module.load_config = lambda: {"timezone": "Europe/Berlin"}
    monkeypatch.setitem(sys.modules, "services.config.config_service", fake_module)
    tz = tu._get_timezone_safe()
    assert tz == "Europe/Berlin"
    tu.clear_timezone_cache()


def test_format_datetime_with_timezone_invalid_tz_falls_back():
    """Invalid tz that's not Europe/Berlin -> UTC fallback wrapper."""
    # An empty timezone name causes ZoneInfo to fail with ValueError
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # tz_name="" forces ZoneInfo to raise ValueError (caught) and pytz to
    # raise UnknownTimeZoneError (caught), then UTC fallback path is taken.
    result = tu.format_datetime_with_timezone(dt, timezone_name="")
    # Either the UTC fallback or another path must produce 2024
    assert "2024" in result or "12:00:00" in result


# =========================================================================== #
# common_helpers.py                                                           #
# =========================================================================== #

def test_hash_container_data_consistent():
    data = {"id": "abc", "status": "running", "image": "nginx:latest"}
    assert ch.hash_container_data(data) == ch.hash_container_data(data)


def test_hash_container_data_different_for_different_inputs():
    a = {"id": "abc", "status": "running", "image": "nginx"}
    b = {"id": "abc", "status": "stopped", "image": "nginx"}
    assert ch.hash_container_data(a) != ch.hash_container_data(b)


def test_hash_container_data_handles_non_dict_returns_timestamp():
    # Passing non-dict triggers exception path -> returns timestamp
    result = ch.hash_container_data(None)  # type: ignore[arg-type]
    assert isinstance(result, (int, float))


def test_safe_get_nested_basic():
    data = {"a": {"b": {"c": 42}}}
    assert ch.safe_get_nested(data, "a.b.c") == 42


def test_safe_get_nested_missing_returns_default():
    assert ch.safe_get_nested({"a": 1}, "a.b.c", default="X") == "X"


def test_safe_get_nested_non_dict_path():
    assert ch.safe_get_nested({"a": "not_dict"}, "a.b", default=None) is None


def test_format_uptime_unknown_for_none():
    assert ch.format_uptime(None) == "Unknown"


def test_format_uptime_unknown_for_negative():
    assert ch.format_uptime(-1) == "Unknown"


def test_format_uptime_minutes_only():
    assert ch.format_uptime(120) == "2m"


def test_format_uptime_hours():
    assert ch.format_uptime(3600 + 600) == "1h 10m"


def test_format_uptime_days():
    assert ch.format_uptime(86400 * 2 + 3600 * 3 + 60 * 5) == "2d 3h 5m"


def test_format_memory_none():
    assert ch.format_memory(None) == "Unknown"


def test_format_memory_negative():
    assert ch.format_memory(-100) == "Unknown"


def test_format_memory_bytes():
    assert ch.format_memory(500) == "500 B"


def test_format_memory_kb():
    assert ch.format_memory(2048) == "2.0 KB"


def test_format_memory_mb():
    assert ch.format_memory(5 * 1024 * 1024) == "5.0 MB"


def test_format_memory_gb():
    assert ch.format_memory(2 * 1024**3) == "2.0 GB"


def test_format_memory_zero():
    # 0 bytes is < 1024 path -> "0 B"
    assert ch.format_memory(0) == "0 B"


def test_format_cpu_percentage_none():
    assert ch.format_cpu_percentage(None) == "Unknown"


def test_format_cpu_percentage_value():
    assert ch.format_cpu_percentage(12.345) == "12.3%"


def test_format_cpu_percentage_invalid():
    assert ch.format_cpu_percentage("xx") == "Unknown"  # type: ignore[arg-type]


def test_truncate_string_no_truncate():
    assert ch.truncate_string("short", max_length=20) == "short"


def test_truncate_string_with_default_suffix():
    assert ch.truncate_string("a" * 50, max_length=10) == "aaaaaaa..."


def test_truncate_string_non_string_input():
    assert ch.truncate_string(12345, max_length=3) == "..."  # type: ignore[arg-type]


def test_validate_container_name_valid():
    assert ch.validate_container_name("nginx") is True
    assert ch.validate_container_name("nginx_1") is True
    assert ch.validate_container_name("a.b-c_d") is True


def test_validate_container_name_invalid():
    assert ch.validate_container_name("") is False
    assert ch.validate_container_name(None) is False  # type: ignore[arg-type]
    assert ch.validate_container_name("-leading-hyphen") is False
    assert ch.validate_container_name(".leading-dot") is False
    assert ch.validate_container_name("has space") is False
    assert ch.validate_container_name("a" * 64) is False


def test_get_current_timestamp_iso():
    ts = ch.get_current_timestamp()
    # Should round-trip via fromisoformat
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


def test_parse_boolean_bool_input():
    assert ch.parse_boolean(True) is True
    assert ch.parse_boolean(False) is False


def test_parse_boolean_string_truthy():
    for v in ["true", "1", "YES", "On", "enabled"]:
        assert ch.parse_boolean(v) is True


def test_parse_boolean_string_falsy():
    assert ch.parse_boolean("nope") is False


def test_parse_boolean_int_input():
    assert ch.parse_boolean(1) is True
    assert ch.parse_boolean(0) is False


def test_parse_boolean_unknown_returns_default():
    assert ch.parse_boolean(None, default=True) is True


def test_sanitize_log_message_token():
    out = ch.sanitize_log_message("token=secret123abc")
    assert "secret123abc" not in out
    assert "***" in out


def test_sanitize_log_message_long_alphanum_replaced():
    out = ch.sanitize_log_message("api_value=" + "A" * 40)
    assert "A" * 40 not in out


def test_sanitize_log_message_non_string_input():
    out = ch.sanitize_log_message(123)  # type: ignore[arg-type]
    assert isinstance(out, str)


def test_is_valid_ip_valid():
    assert ch.is_valid_ip("127.0.0.1") is True


def test_is_valid_ip_invalid():
    assert ch.is_valid_ip("not.an.ip.addr") is False


def test_validate_ip_format_empty_is_valid():
    assert ch.validate_ip_format("") is True


def test_validate_ip_format_with_port():
    assert ch.validate_ip_format("192.168.1.1:8080") is True


def test_validate_ip_format_localhost():
    assert ch.validate_ip_format("localhost") is True


def test_validate_ip_format_invalid_chars():
    assert ch.validate_ip_format("not valid!!") is False


def test_batch_process_basic():
    assert ch.batch_process([1, 2, 3, 4, 5], batch_size=2) == [[1, 2], [3, 4], [5]]


def test_batch_process_empty_returns_empty():
    assert ch.batch_process([], batch_size=10) == []


def test_batch_process_zero_size_returns_empty():
    assert ch.batch_process([1, 2, 3], batch_size=0) == []


def test_deep_merge_dicts_basic():
    a = {"x": 1, "y": {"a": 1}}
    b = {"y": {"b": 2}, "z": 3}
    merged = ch.deep_merge_dicts(a, b)
    assert merged == {"x": 1, "y": {"a": 1, "b": 2}, "z": 3}


def test_deep_merge_dicts_overwrites_non_dict():
    a = {"k": 1}
    b = {"k": 2}
    assert ch.deep_merge_dicts(a, b) == {"k": 2}


def test_retry_on_exception_eventually_succeeds():
    calls = {"n": 0}

    @ch.retry_on_exception(max_retries=2, delay=0.001, backoff=1.0)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("retry me")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 2


def test_retry_on_exception_raises_after_max():
    @ch.retry_on_exception(max_retries=1, delay=0.001, backoff=1.0)
    def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        always_fails()


def test__is_valid_ip_internal():
    assert ch._is_valid_ip("10.0.0.1") is True
    assert ch._is_valid_ip("999.999.999.999") is False
