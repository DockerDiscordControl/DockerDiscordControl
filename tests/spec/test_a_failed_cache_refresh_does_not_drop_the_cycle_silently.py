# -*- coding: utf-8 -*-
"""A failed cache refresh says so, and does not leave coroutines unawaited.

THE FINDING: the periodic edit loop builds the coroutines for this cycle's
message edits and then refreshes the status cache - outside the try that
guards the batch run. When that refresh raises, the loop guard swallows the
exception, the already-built coroutines are garbage-collected without ever
being awaited ("coroutine ... was never awaited" on stderr), and the DDC log
says nothing about the cycle that was lost.

The refresh is its own guarded step now: a failure is logged with its reason
and the cycle carries on with whatever the cache holds - stale data with an
age next to it (the overview says how old it is) beats no update at all.

COUNTER-CHECK (2026-09-22): red before - the run left a warning about an
unawaited coroutine and no error line.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.docker_control import DockerControlCog


@pytest.mark.asyncio
async def test_a_refresh_that_raises_is_logged_and_never_escapes(caplog):
    cog = object.__new__(DockerControlCog)

    async def _boom():
        raise RuntimeError("docker is busy")

    cog._ensure_status_cache_fresh = _boom

    with caplog.at_level(logging.DEBUG):
        await cog._refresh_cache_for_cycle()      # must not raise

    said = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    assert "docker is busy" in said, f"nothing says the refresh failed: {said}"


@pytest.mark.asyncio
async def test_a_working_refresh_stays_quiet(caplog):
    """Counter-check: the ordinary cycle must not log a warning."""
    cog = object.__new__(DockerControlCog)
    cog._ensure_status_cache_fresh = AsyncMock()

    with caplog.at_level(logging.DEBUG):
        await cog._refresh_cache_for_cycle()

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    cog._ensure_status_cache_fresh.assert_awaited_once()


def test_the_loop_uses_it():
    """The edit loop must go through the guarded call, not the raw one."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "cogs" / "message_updates.py"
    text = source.read_text(encoding="utf-8")
    body = text[text.index("if tasks_to_run:"):text.index("ULTRA-PERFORMANCE: Batched")]
    assert "_refresh_cache_for_cycle()" in body
    assert "await self._ensure_status_cache_fresh()" not in body
