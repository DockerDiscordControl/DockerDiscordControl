# -*- coding: utf-8 -*-
# @covers Z3
"""Z3 - a container action that failed is reported as failed.

THE FINDING (stage 4 review pass 1, section 02 F2, re-checked 2026-09-19):
``run_docker_action`` (cogs/control_ui.py, ActionButton) awaited
``docker_action_service_first`` and only LOGGED its result. A failed start,
stop or restart (success=False - the service turns Docker errors into that)
went on exactly like a successful one: "Processing... please wait", then the
unchanged status. The user was never told the action had failed. (The
reviewer's other claim - the pending state sticks forever - is refuted: the
task's done-callback always clears it.)

HOW IT IS CHECKED: the button callback runs for real, as in
test_processing_message_fits_narrow_screens.py; the background task is
captured and run, waits are skipped, ``_`` is replaced by a marker.
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


def _run(monkeypatch, success):
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})
    monkeypatch.setattr(cui, "_get_cached_channel_permission",
                        lambda channel_id, key, config=None: True)
    monkeypatch.setattr(cui, "log_user_action", MagicMock())
    servers = MagicMock()
    servers.get_all_servers.return_value = []
    monkeypatch.setattr(cui, "get_server_config_service", lambda: servers)
    monkeypatch.setattr(
        "services.docker_service.docker_action_service.docker_action_service_first",
        AsyncMock(return_value=success))
    monkeypatch.setattr(
        "services.infrastructure.container_status_service.get_container_status_service",
        lambda: MagicMock())
    monkeypatch.setattr(cui, "_", lambda text: f"«{text}»")
    proxy = _AsyncioProxy()
    monkeypatch.setattr(cui, "asyncio", proxy)

    button = ActionButton.__new__(ActionButton)
    button.cog = SimpleNamespace(pending_actions={}, status_cache_service=MagicMock())
    button.action = "start"
    button.server_config = {"docker_name": "vrising", "display_name": "V-Rising",
                            "allowed_actions": ["start", "stop", "restart"]}
    button.docker_name = "vrising"
    button.display_name = "V-Rising"
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
    embeds = [c.kwargs.get("embed") for c in inter.edit_original_response.await_args_list]
    return [f"{e.title or ''} {e.description or ''}" for e in embeds if e is not None]


def test_a_failed_action_is_reported_as_failed(monkeypatch):
    shown = _run(monkeypatch, success=False)
    failed = [s for s in shown if "Server Action Failed" in s]
    assert failed, f"the action failed, the user saw only: {shown}"
    assert "V-Rising" in failed[0], "the failure message does not say which container"
    assert not any("Processing" in s for s in shown), "'processing' shown for a failed action"


def test_a_successful_action_is_not_reported_as_a_failure(monkeypatch):
    """Counter-check: success must not be reported as failure.

    It looked for the word "Processing", which was the message announcing a
    blind fifteen-second wait. That message went on 2026-09-24 together with
    the wait, leaving the pending embed as what a press shows - so the case
    names that instead. What it is actually guarding, the absence of a failure
    notice after a successful action, is unchanged.
    """
    shown = _run(monkeypatch, success=True)

    assert any("Pending" in s for s in shown), shown
    assert not any("Server Action Failed" in s for s in shown), shown
