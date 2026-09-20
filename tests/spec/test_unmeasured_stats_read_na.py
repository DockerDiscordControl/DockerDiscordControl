# -*- coding: utf-8 -*-
"""A value that was not measured reads N/A, not 0.0.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 08 F3, re-checked 2026-09-20):
``get_status`` read the stats as ``stats_dict.get('cpu_percent', 0.0)`` and
``stats_dict.get('memory_usage_mb', 0.0)``. A stats answer that carries one
key but not the other therefore became a confident "0.0%" or "0.0 MB" in the
panel - a number nobody measured, and one that reads like an idle container
rather than like a missing reading. The line right below it, ``if cpu_percent
is not None else 'N/A'``, shows the intent: a missing value should read N/A.
The bulk path a few hundred lines up gets this right (``stats.get('cpu_
percent')``, no default), so the same container could read "0.0%" in one view
and "N/A" in the other.
"""

from unittest.mock import AsyncMock, patch

import pytest

from cogs.status_handlers import StatusHandlersMixin

SERVER = {"name": "Test", "docker_name": "test_container", "display_name": "Test",
          "allow_detailed_status": True}
RUNNING = {"State": {"Status": "running", "Running": True,
                     "StartedAt": "2025-01-01T00:00:00Z"},
           "Name": "/test_container"}


async def _status(stats):
    mixin = StatusHandlersMixin()
    mixin.bot = None
    with patch("cogs.status_handlers.get_docker_info_dict_service_first",
               new_callable=AsyncMock, return_value=RUNNING), \
         patch("cogs.status_handlers.get_docker_stats_service_first",
               new_callable=AsyncMock, return_value=stats):
        return await mixin.get_status(SERVER)


@pytest.mark.asyncio
async def test_measured_values_are_shown():
    """Premise: a complete answer still renders the real numbers."""
    result = await _status({"cpu_percent": 10.5, "memory_usage_mb": 256.0})

    assert result.cpu == "10.5%"
    assert result.ram == "256.0 MB"


@pytest.mark.asyncio
async def test_a_missing_cpu_reads_na():
    result = await _status({"memory_usage_mb": 256.0})

    assert result.cpu == "N/A", f"no CPU value was measured, the panel shows {result.cpu}"
    assert result.ram == "256.0 MB", "the value that WAS measured must still be shown"


@pytest.mark.asyncio
async def test_a_missing_memory_reads_na():
    result = await _status({"cpu_percent": 10.5})

    assert result.ram == "N/A", f"no memory value was measured, the panel shows {result.ram}"
    assert result.cpu == "10.5%"


@pytest.mark.asyncio
async def test_a_real_zero_is_still_shown():
    """Counter-check: a measured zero is a reading and must not turn into N/A."""
    result = await _status({"cpu_percent": 0.0, "memory_usage_mb": 0.0})

    assert result.cpu == "0.0%"
    assert result.ram == "0.0 MB"
