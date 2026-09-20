# -*- coding: utf-8 -*-
"""A measurement that failed is not replaced by a plausible number.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage C, section 19 F1, re-checked 2026-09-20):
when Docker's stats call fails for a running container,
``_query_container_sync`` writes cpu_percent=0.1, memory_usage_mb=2.0,
memory_limit_mb=1024.0 into the result and returns it with success=True. The
two helpers do the same on their own: ``_calculate_cpu_percent_from_stats``
answers 0.1 for every failure - and for a container that genuinely used no
CPU - and ``_calculate_memory_from_stats`` answers (2.0, 1024.0) whenever it
cannot read the numbers.

So a container whose monitoring is broken looks like a healthy, almost idle
one: "0.1 %, 2.0 MB of 1024 MB". The path that carries these numbers into
Discord already renders None as "N/A" (review B20) - it was never given the
chance.
"""

from unittest.mock import MagicMock

import pytest

from services.infrastructure.container_status_service import (ContainerStatusRequest,
                                                              ContainerStatusService)

WORKING_STATS = {
    "cpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 1000,
                  "online_cpus": 2},
    "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
    "memory_stats": {"usage": 1024 * 1024 * 100, "limit": 1024 * 1024 * 500},
}


def _service():
    return ContainerStatusService()


def _container(stats):
    container = MagicMock()
    container.status = "running"
    container.attrs = {"State": {"Status": "running", "Running": True,
                                 "StartedAt": "2025-01-01T00:00:00Z"},
                       "Config": {"Image": "test:latest"},
                       "NetworkSettings": {"Ports": {}}}
    if isinstance(stats, Exception):
        container.stats.side_effect = stats
    else:
        container.stats.return_value = stats
    return container


def _query(stats):
    client = MagicMock()
    client.containers.get.return_value = _container(stats)
    request = ContainerStatusRequest(container_name="vrising", include_stats=True)
    return _service()._query_container_sync(client, request, 0.0)


def test_real_numbers_are_still_measured():
    """Premise: with usable stats the real values come out."""
    service = _service()

    assert service._calculate_cpu_percent_from_stats(WORKING_STATS, "x") == pytest.approx(40.0)
    assert service._calculate_memory_from_stats(WORKING_STATS, "x") == (
        pytest.approx(100.0), pytest.approx(500.0))


def test_a_cpu_reading_that_failed_is_not_invented():
    unavailable = _service()._calculate_cpu_percent_from_stats(None, "x")

    assert unavailable is None, f"a failed CPU reading came back as {unavailable}"


def test_a_memory_reading_that_failed_is_not_invented():
    usage, limit = _service()._calculate_memory_from_stats({}, "x")

    assert usage is None and limit is None, (
        f"a failed memory reading came back as {usage} of {limit}"
    )


def test_a_container_that_used_no_cpu_reads_zero():
    """Counter-check: a measured zero is a measurement, not a failure."""
    idle = dict(WORKING_STATS,
                cpu_stats={"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000,
                           "online_cpus": 2},
                precpu_stats={"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500})

    assert _service()._calculate_cpu_percent_from_stats(idle, "x") == 0.0


def test_the_whole_query_does_not_invent_stats():
    result = _query(RuntimeError("stats endpoint gone"))

    assert result.cpu_percent is None and result.memory_usage_mb is None, (
        f"the query invented {result.cpu_percent} % and {result.memory_usage_mb} MB"
    )


def test_the_whole_query_still_reports_real_stats():
    """Counter-check: nothing about the working path changes."""
    result = _query(WORKING_STATS)

    assert result.success is True
    assert result.cpu_percent == pytest.approx(40.0)
    assert result.memory_usage_mb == pytest.approx(100.0)
