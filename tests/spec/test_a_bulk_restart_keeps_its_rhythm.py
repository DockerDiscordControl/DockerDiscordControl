# -*- coding: utf-8 -*-
"""The pause between two containers counts attempts, not successes.

THE FINDING: the bulk restart puts half a second between operations "to avoid
overloading", but the delay was tied to restarted_count - the number of
SUCCESSFUL restarts. On a daemon that is already struggling, where the calls
fail or time out, that counter stays at zero and no pause is ever inserted:
fifty containers hit the daemon back to back, in exactly the situation the
pause was written for.

COUNTER-CHECK (2026-09-22): red before - with every call failing, no sleep
happened at all. The second test keeps the pause out of the first call.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.admin_overview as ao
from services.docker_status.models import ContainerStatusResult

SERVERS = [{"docker_name": name, "allowed_actions": ["restart"]} for name in ("a", "b", "c")]


@pytest.fixture
def running(monkeypatch):
    def _entry(name):
        return {"data": ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1MB",
            uptime="1h", details_allowed=True)}

    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: type("C", (), {"get": staticmethod(lambda n: _entry(n))})())
    sleeps = []

    async def _sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(ao.asyncio, "sleep", _sleep)
    return sleeps


def _counts(sleeps, result):
    async def action(name, verb):
        return result

    return asyncio.run(ao._restart_running_servers(SERVERS, action))


def test_a_failing_run_is_paced_too(running):
    counts = _counts(running, False)

    assert counts["failed"] == 3
    assert running == [0.5, 0.5], (
        "three containers hit a struggling daemon with no pause at all")


def test_a_successful_run_pauses_between_containers(running):
    counts = _counts(running, True)

    assert counts["restarted"] == 3
    assert running == [0.5, 0.5], "the pause belongs between containers, not before the first"
