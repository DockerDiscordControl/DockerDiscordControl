# -*- coding: utf-8 -*-
"""An action that outlasts the pending mark does not clear the next press's mark.

THE FINDING (stage 4 review before v3.1.0, section 02 pass 3 F2): a press
marks the container as pending; a mark older than 120 s counts as stale, so a
second press gets through while a long stop or restart (a container with a
long StopTimeout, a big group) still runs. When the FIRST action returned,
ActionButton deleted the pending entry without looking whose it was - the
SECOND press's. Its panel stopped showing "pending", and a third press was
let through while the second was still running. Three of the deletions
already checked identity; five did not.

THE CONTRACT: an action only ever takes back its own mark.

HOW THIS TEST CAN FAIL: the first action's end deletes the second press's
mark (success, failure, or an exception on the way).

COUNTER-CHECK (2026-09-29): the success and the exception case red before
the change; the failure path already checked identity and is green on both
sides.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton

SECOND = {"action": "stop", "timestamp": None, "user": "second press"}


class _AsyncioProxy:
    def __init__(self):
        self.tasks = []
        self.sleep = AsyncMock()

    def create_task(self, coro):
        self.tasks.append(coro)
        return MagicMock()

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _press(monkeypatch, outcome):
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})
    from tests.spec import configured_as_drawn
    configured_as_drawn(monkeypatch, cui)
    monkeypatch.setattr(cui, "_get_cached_channel_permission",
                        lambda channel_id, key, config=None: True)
    monkeypatch.setattr(cui, "log_user_action", MagicMock())
    servers = MagicMock()
    servers.get_all_servers.return_value = []
    servers.get_server_by_docker_name.side_effect = lambda name: {
        "docker_name": name, "allowed_actions": ["start", "stop", "restart"]}
    monkeypatch.setattr(cui, "get_server_config_service", lambda: servers)
    cog = SimpleNamespace(pending_actions={}, status_cache_service=MagicMock())

    async def _docker(name, action):
        cog.pending_actions[name] = SECOND  # the second press, while this one ran
        if outcome == "raise":
            raise KeyError("status lookup fell over")
        return outcome
    monkeypatch.setattr(
        "services.docker_service.docker_action_service.docker_action_service_first", _docker)
    proxy = _AsyncioProxy()
    monkeypatch.setattr(cui, "asyncio", proxy)

    button = ActionButton.__new__(ActionButton)
    button.cog = cog
    button.action = "stop"
    button.server_config = {"docker_name": "web", "display_name": "web",
                            "allowed_actions": ["start", "stop", "restart"]}
    button.docker_name = "web"
    button.display_name = "web"
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = 4711
    inter.channel.id = 300
    inter.message = None

    async def go():
        await button.callback(inter)
        await proxy.tasks.pop(0)          # run_docker_action
        for leftover in proxy.tasks:
            leftover.close()

    asyncio.run(go())
    return cog.pending_actions.get("web")


@pytest.mark.parametrize("outcome", [True, False, "raise"])
def test_the_first_action_leaves_the_second_mark_alone(monkeypatch, outcome):
    assert _press(monkeypatch, outcome) is SECOND, (
        f"the first action ({outcome}) took back the mark of the second press")
