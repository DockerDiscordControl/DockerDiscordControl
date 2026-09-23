# -*- coding: utf-8 -*-
"""Restarting a group from Discord says who was not touched.

THE FINDING (independent review, 2026-09-23): two paths act on the same group
and judge it differently. A scheduled task reports a FAILURE when the group
has lost a member ("no longer in DDC: ..."), which is the rule the group
service was built around. The Discord button dropped them silently: members
DDC no longer has are filtered out of the menu, inactive ones are filtered out
again when the restart runs, and the summary is green over what is left.

A group of seven with two renamed away and one inactive: the menu says five,
four are restarted, the embed is green, and nobody is told about the three.

The summary now names them. Restarting the rest is right - that is what the
button is for - but reporting it as the whole group is not.

COUNTER-CHECK (2026-09-23): red before - the summary held nothing about the
missing members, and test_a_complete_group_says_nothing_extra keeps the
ordinary case free of noise.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import cogs.admin_overview as ao
from cogs import stack_restart
from services.docker_status.models import ContainerStatusResult

CHANNEL = 42


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Three configured containers, one of them inactive, and a group of four."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "Icarus 1", "Sleeper"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status", "restart"]}),
            encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    # "Gone" is not configured at all; "Sleeper" is configured but inactive
    group_service.get_group_service().save_group(
        "Gameserver", ["Valheim", "Icarus 1", "Sleeper", "Gone"])

    servers = [{"docker_name": "Valheim", "active": True, "allowed_actions": ["restart"]},
               {"docker_name": "Icarus 1", "active": True, "allowed_actions": ["restart"]},
               {"docker_name": "Sleeper", "active": False, "allowed_actions": ["restart"]}]

    def _entry(name):
        return {"data": ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1MB",
            uptime="1h", details_allowed=True)}

    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))
    monkeypatch.setattr(ao, "get_status_cache_service", lambda: SimpleNamespace(get=_entry))
    monkeypatch.setattr(ao, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=AsyncMock(return_value=True)))
    monkeypatch.setattr(ao.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr("services.docker_service.docker_action_service.docker_action_service_first",
                        AsyncMock(return_value=True))
    return SimpleNamespace(servers=servers)


async def _restart(group):
    cog = SimpleNamespace(_bulk_operation_in_progress=False,
                          bot=SimpleNamespace(get_channel=lambda cid: None))
    interaction = SimpleNamespace(
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        user=SimpleNamespace(id=7), channel=SimpleNamespace(id=CHANNEL))
    await stack_restart.ConfirmRestartStackButton(cog, CHANNEL, group).callback(interaction)
    return interaction.followup.send.await_args.kwargs["embed"].description


@pytest.mark.asyncio
async def test_the_summary_names_the_members_it_could_not_touch(world):
    description = await _restart("Gameserver")

    assert "Gone" in description, f"a member DDC no longer has went unmentioned: {description}"
    assert "Sleeper" in description, f"an inactive member went unmentioned: {description}"


@pytest.mark.asyncio
async def test_a_complete_group_says_nothing_extra(world):
    """Counter-check: the ordinary case must stay free of noise."""
    from services.config import group_service

    group_service.get_group_service().save_group("Gameserver", ["Valheim", "Icarus 1"])

    description = await _restart("Gameserver")

    assert "Gone" not in description and "Sleeper" not in description
    assert "not" not in description.lower() or "restarted" in description.lower(), description
