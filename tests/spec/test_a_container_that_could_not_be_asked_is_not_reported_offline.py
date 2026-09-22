# -*- coding: utf-8 -*-
"""A container DDC could not ask is "unknown", never "offline" (Z3, again).

THE FINDING: a container whose Docker query fails - the inspect times out,
the daemon is busy, the socket hiccups - was reported as a SUCCESSFUL
measurement saying "not running" (`offline_result`, success=True,
is_running=False). A container that really is stopped answers `inspect`
normally with State.Running false, so that branch is reached almost only
when nothing could be measured at all.

What followed from it:
* the container watchdog (Phase 4a) saw running -> not running and raised a
  "container stopped" alarm for a container that never went down. A rule
  with a restart action would restart a healthy container, and the false
  event burns the rule's cooldown, so the REAL stop later is skipped;
* the Discord overview counted it as offline - the very thing SPEC.md Z3
  forbids for a container nobody could ask.

A failed query is now an error result: the status cache keeps the last
known state (a non-success result is not written), the overview shows the
loading icon and does not count it, and the watchdog ignores it.

COUNTER-CHECK (2026-09-22): red before - the timed-out container produced a
"stopped" event and a success result.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cogs.docker_control import DockerControlCog
from services.docker_status.models import ContainerStatusResult

CONFIG = {"name": "Web", "docker_name": "web", "display_name": "Web", "allow_detailed_status": True}


def _mixin():
    cog = object.__new__(DockerControlCog)
    cog.pending_actions = {}
    return cog


def _not_missing():
    return SimpleNamespace(is_container_not_found=lambda name: False)


def test_a_timed_out_query_is_an_error_not_an_offline_container():
    with patch("cogs.status_handlers.get_docker_info_dict_service_first",
               new_callable=AsyncMock, return_value=None), \
         patch("cogs.status_handlers.get_container_status_service", _not_missing):
        result = asyncio.run(_mixin().get_status(CONFIG))

    assert result.success is False, (
        "a container that could not be asked is reported as a successful measurement "
        "saying 'not running' - the watchdog alarms and the overview counts it offline")
    assert result.is_running is False and result.not_found is False


def test_a_container_that_docker_says_is_gone_is_still_not_found():
    """Counter-check: turning every empty answer into an error would lose this."""
    with patch("cogs.status_handlers.get_docker_info_dict_service_first",
               new_callable=AsyncMock, return_value=None), \
         patch("cogs.status_handlers.get_container_status_service",
               lambda: SimpleNamespace(is_container_not_found=lambda name: True)):
        result = asyncio.run(_mixin().get_status(CONFIG))

    assert result.success is True and result.not_found is True


def test_a_stopped_container_is_still_offline():
    """Counter-check, the other side: Docker answers for a stopped container."""
    info = {"State": {"Running": False}, "Config": {"Image": "nginx"}, "RestartCount": 0}
    with patch("cogs.status_handlers.get_docker_info_dict_service_first",
               new_callable=AsyncMock, return_value=info), \
         patch("cogs.status_handlers.get_container_status_service", _not_missing):
        result = asyncio.run(_mixin().get_status(CONFIG))

    assert result.success is True and result.is_running is False and result.is_offline is True


@pytest.mark.asyncio
async def test_the_bulk_fetch_reports_a_failed_query_as_a_failure():
    """The path the status loop uses, with the fetch service's timeout answer."""
    cog = _mixin()

    async def _retries(name):
        # what fetch_with_retries returns when every retry AND the emergency fetch timed out
        return name, TimeoutError("inspect timed out"), None

    classification = SimpleNamespace(fast_containers=["web"], slow_containers=[], unknown_containers=[])
    with patch("services.infrastructure.docker_connectivity_service.get_docker_connectivity_service",
               lambda: SimpleNamespace(check_connectivity=AsyncMock(
                   return_value=SimpleNamespace(is_connected=True, error_message=None)))), \
         patch("cogs.status_handlers.get_performance_service",
               lambda: SimpleNamespace(classify_containers=lambda names: classification,
                                       update_performance=lambda *a, **kw: None)), \
         patch("cogs.status_handlers.get_fetch_service",
               lambda: SimpleNamespace(fetch_with_retries=_retries)), \
         patch("cogs.status_handlers.get_server_config_service",
               lambda: SimpleNamespace(get_all_servers=lambda: [CONFIG])), \
         patch("cogs.status_handlers.get_container_status_service", _not_missing):
        results = await cog.bulk_fetch_container_status(["web"])

    assert results["web"].success is False, (
        "the status loop writes this into the cache as 'not running' and the watchdog alarms")


@pytest.mark.asyncio
async def test_the_watchdog_gets_no_event_from_a_failed_query():
    """The reason this matters: no alarm, and no restart of a healthy container."""
    from services.automation.auto_action_config_service import AutoActionRule
    from services.automation import automation_service as engine_module

    cog = _mixin()
    rules = [AutoActionRule.from_dict({"id": "r", "name": "Watch", "trigger":
                                       {"type": "container_state", "states": ["stopped"]},
                                       "action": {"type": "NOTIFY"}})]
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    with patch("services.automation.auto_action_config_service.get_auto_action_config_service",
               lambda: SimpleNamespace(get_rules=lambda: rules)), \
         patch.object(engine_module, "get_automation_service", lambda: engine):
        running = ContainerStatusResult.success_result(
            docker_name="web", display_name="Web", is_running=True, cpu="1%", ram="1MB",
            uptime="1h", details_allowed=True)
        await cog._feed_container_watchdog({"web": running}, {})
        failed = ContainerStatusResult.error_result(
            docker_name="web", error=TimeoutError("inspect timed out"), error_type="fetch")
        await cog._feed_container_watchdog({"web": failed}, {})

    events = [e for call in engine.process_container_events.await_args_list for e in call.args[0]]
    assert events == [], f"a query that failed raised {[(e.container, e.kind) for e in events]}"
