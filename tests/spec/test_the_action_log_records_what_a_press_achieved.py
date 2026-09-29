# -*- coding: utf-8 -*-
"""The action log records what a Discord button press achieved, not what it tried.

THE FINDING (stage 4 review before v3.1.0, section 02 pass 4 F3): the
Start/Stop/Restart button wrote DOCKER_STOP (etc.) to the action log BEFORE
the action ran and never recorded the outcome. A refused or failed action
appeared in the web panel's action log as done. Every other writer of
container actions records the result: the scheduler (STOP vs STOP_FAILED /
_ERROR), the group tasks (X_GROUP vs X_GROUP_FAILED).

THE CONTRACT: DOCKER_<ACTION> once Docker has done it; DOCKER_<ACTION>_FAILED
when Docker refused; DOCKER_<ACTION>_ERROR when the press fell over before
Docker answered.

HOW THIS TEST CAN FAIL: a failed or broken press is logged as done again, or
a successful one is not logged at all.

COUNTER-CHECK (2026-09-29): the failure and error cases red before the
change; the success case green before and after.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton


class _AsyncioProxy:
    def __init__(self):
        self.tasks = []
        self.sleep = AsyncMock()

    def create_task(self, coro):
        self.tasks.append(coro)
        return MagicMock()

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _logged(monkeypatch, outcome):
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
    log = MagicMock()
    monkeypatch.setattr(cui, "log_user_action", log)
    servers = MagicMock()
    servers.get_all_servers.return_value = []
    servers.get_server_by_docker_name.side_effect = lambda name: {
        "docker_name": name, "allowed_actions": ["start", "stop", "restart"]}
    monkeypatch.setattr(cui, "get_server_config_service", lambda: servers)

    async def _docker(name, action):
        if outcome == "raise":
            raise KeyError("status lookup fell over")
        return outcome
    monkeypatch.setattr(
        "services.docker_service.docker_action_service.docker_action_service_first", _docker)
    proxy = _AsyncioProxy()
    monkeypatch.setattr(cui, "asyncio", proxy)

    button = ActionButton.__new__(ActionButton)
    button.cog = SimpleNamespace(pending_actions={}, status_cache_service=MagicMock())
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
    return [c.kwargs.get("action") for c in log.call_args_list]


@pytest.mark.parametrize("outcome,expected", [
    (True, ["DOCKER_STOP"]),
    (False, ["DOCKER_STOP_FAILED"]),
    ("raise", ["DOCKER_STOP_ERROR"]),
])
def test_the_log_says_what_happened(monkeypatch, outcome, expected):
    assert _logged(monkeypatch, outcome) == expected
