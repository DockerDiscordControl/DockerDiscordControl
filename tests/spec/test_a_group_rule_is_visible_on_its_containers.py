# -*- coding: utf-8 -*-
"""The rules shown for a container include the ones that reach it via a group.

THE FINDING (independent review, 2026-09-23): the "Auto-Actions for this
container" button filters with `self.container_name in rule.action.containers`
- the raw list. A rule targeting "group:Gameserver" that will stop `Valheim`
therefore does not appear under Valheim, and the button answers "No
Auto-Actions configured for this container" while an automation is wired to
it. That is the one call site the group resolution did not reach.

COUNTER-CHECK (2026-09-23): red before - the group rule was invisible, and the
second test keeps the filter from becoming "show everything".
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule


def _rule(name, containers):
    return AutoActionRule.from_dict({
        "id": name, "name": name, "enabled": True,
        "trigger": {"type": "message", "channel_ids": [], "keywords": ["x"]},
        "action": {"type": "STOP", "containers": containers},
    })


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "plex"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status"]}),
            encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    group_service.get_group_service().save_group("Gameserver", ["Valheim"])

    rules = [_rule("group rule", ["group:Gameserver"]), _rule("plex rule", ["plex"])]
    # Patched where the BUTTON looks it up: cogs.task_ui binds the name at
    # import (line 22), so patching services.automation reached nothing once
    # the module was already imported - green alone, red in the group run.
    import cogs.task_ui as task_ui

    monkeypatch.setattr(task_ui, "get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: rules))
    return rules


async def _shown_for(container):
    from cogs.task_ui import AutoActionButton

    interaction = SimpleNamespace(
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()))
    await AutoActionButton(None, container).callback(interaction)
    embed = interaction.followup.send.await_args.kwargs["embed"]
    return (embed.description or "") + " ".join(
        f"{field.name} {field.value}" for field in embed.fields)


@pytest.mark.asyncio
async def test_a_rule_that_reaches_the_container_through_a_group_is_shown(world):
    shown = await _shown_for("Valheim")

    assert "group rule" in shown, (
        "an automation that stops this container is reported as not existing")


@pytest.mark.asyncio
async def test_a_rule_for_another_container_is_not_shown(world):
    """Counter-check: resolving must not turn the filter into "show all"."""
    shown = await _shown_for("Valheim")

    assert "plex rule" not in shown
