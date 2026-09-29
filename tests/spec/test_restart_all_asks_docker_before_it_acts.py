# -*- coding: utf-8 -*-
"""Restart All / Stop All ask Docker whether a container still runs before acting.

THE FINDING (stage 4 review before v3.1.0, section 01 pass 4 F8): the bulk
actions decided "running" from the status cache alone. A container stopped
outside DDC within the last status beat (30 s by default; an entry lives up
to 75 s) still counted as running - and `docker restart` STARTED it, counted
as "Successfully restarted", although the confirmation promised to touch
running containers only.

THE CONTRACT: a container the cache calls running is asked again, fresh,
before the action; not running -> skipped (not running); not readable ->
not checked. The single-container path already asks fresh
(cogs/action_effect.py).

HOW THIS TEST CAN FAIL: a stopped container is restarted on the cache's word.

COUNTER-CHECK (2026-09-29): red before the change; the case where the fresh
read confirms "running" is green before and after.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.admin_overview as ao
from services.docker_status.models import ContainerStatusResult


def _cached_running(name):
    return {"data": ContainerStatusResult.success_result(
        docker_name=name, display_name=name, is_running=True,
        cpu="1%", ram="1MB", uptime="1h", details_allowed=True)}


def _world(monkeypatch, fresh_running):
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: SimpleNamespace(is_enabled=lambda: False))
    servers = [{"docker_name": "x", "active": True, "allowed_actions": ["restart", "stop"]}]
    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))
    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: SimpleNamespace(get=_cached_running))

    async def _admin(uid):
        return True
    monkeypatch.setattr(ao, "get_admin_service", lambda: SimpleNamespace(
        is_user_admin_async=_admin, controllable=lambda uid, items: items))
    live = SimpleNamespace(
        invalidate_container=lambda name: True,
        get_container_status=AsyncMock(return_value=SimpleNamespace(
            success=True, is_running=fresh_running)))
    monkeypatch.setattr("services.infrastructure.container_status_service.get_container_status_service",
                        lambda: live)
    acted = []

    async def _action(name, verb):
        acted.append((name, verb))
        return True
    monkeypatch.setattr("services.docker_service.docker_action_service.docker_action_service_first", _action)
    monkeypatch.setattr(ao.asyncio, "sleep", AsyncMock())
    said = AsyncMock()
    monkeypatch.setattr(ao, "answer_or_post", said)
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.user.id = 4711
    return acted, said, inter


async def test_a_container_that_stopped_since_the_last_beat_is_not_started(monkeypatch):
    acted, said, inter = _world(monkeypatch, fresh_running=False)
    button = ao.ConfirmRestartAllButton(SimpleNamespace(_bulk_operation_in_progress=False), 300)
    button._refresh_overview_later = AsyncMock()
    await button.callback(inter)
    assert acted == [], "the cache said running, Docker said stopped, and it was restarted"
    text = said.await_args.args[3].description
    assert "Skipped (not running): **1**" in text, text


async def test_a_running_container_is_still_restarted(monkeypatch):
    acted, _, inter = _world(monkeypatch, fresh_running=True)
    button = ao.ConfirmRestartAllButton(SimpleNamespace(_bulk_operation_in_progress=False), 300)
    button._refresh_overview_later = AsyncMock()
    await button.callback(inter)
    assert acted == [("x", "restart")]
