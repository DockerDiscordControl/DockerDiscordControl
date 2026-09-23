# -*- coding: utf-8 -*-
"""A rule acting on many containers announces itself once, not once each.

THE FINDING (independent review, 2026-09-23): the announcement before the
action is sent PER CONTAINER. One ticked group of 200 members is 200 messages
per trigger, into one channel, and Discord's rate limit stops them long before
the containers are done. The skipped-by-only_if_running notices were
deliberately consolidated into a single line for this very reason; this path
was not.

The announcement names the containers it is about, in one message. A rule on a
single container reads exactly as it did before.

COUNTER-CHECK (2026-09-23): red before - five containers produced five
messages. test_a_single_container_reads_as_before keeps the everyday case, and
test_the_action_still_reaches_every_container makes sure consolidating the
message did not consolidate the work.
"""

import json
from types import SimpleNamespace

import pytest

from services.automation.auto_action_config_service import AutoActionRule

CONTAINERS = ["web", "db", "cache", "queue", "mail"]


def _rule(containers):
    return AutoActionRule.from_dict({
        "id": "r1", "name": "big rule", "enabled": True,
        "trigger": {"type": "message", "channel_ids": [], "keywords": ["x"]},
        "action": {"type": "RESTART", "containers": list(containers)},
    })


@pytest.fixture
def service(monkeypatch):
    from services.automation import automation_service as module

    acted = []
    messages = []

    async def docker_action(name, action):
        acted.append(name)
        return True, ""

    async def exists(name):
        return True

    monkeypatch.setattr(module, "docker_action", docker_action)
    monkeypatch.setattr(module, "is_container_exists", exists)

    service = module.AutomationService()
    service.state_service = SimpleNamespace(
        record_trigger=lambda *a, **k: None,
        acquire_execution_locks=lambda *a, **k: (True, "", None),
        release_execution_lock=lambda *a, **k: None,
        release_execution_locks=lambda *a, **k: None,
        release_rule_cooldown=lambda *a, **k: None)

    async def send(bot, channel_id, text):
        messages.append(text)

    service._send_feedback = send

    async def not_running(*args, **kwargs):
        return False

    service._honours_only_if_running = not_running
    return SimpleNamespace(service=service, acted=acted, messages=messages)


async def _run(world, containers):
    context = SimpleNamespace(message=None, channel_id=9, message_link="https://x")
    await world.service._execute_rule(_rule(containers), context,
                                      {"protected_containers": []}, bot=object())


@pytest.mark.asyncio
async def test_five_containers_are_announced_in_one_message(service):
    await _run(service, CONTAINERS)

    announcements = [m for m in service.messages if "RESTART" in m]

    assert len(announcements) == 1, (
        f"{len(announcements)} messages for {len(CONTAINERS)} containers - a group of 200 "
        f"would hit Discord's rate limit")
    for container in CONTAINERS:
        assert container in announcements[0], announcements[0]


@pytest.mark.asyncio
async def test_the_action_still_reaches_every_container(service):
    """Counter-check: one message must not mean one container."""
    await _run(service, CONTAINERS)

    assert service.acted == CONTAINERS


@pytest.mark.asyncio
async def test_a_single_container_reads_as_before(service):
    await _run(service, ["web"])

    announcements = [m for m in service.messages if "RESTART" in m]

    assert len(announcements) == 1
    assert "**web**" in announcements[0], announcements[0]
