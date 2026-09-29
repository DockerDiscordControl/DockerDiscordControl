# -*- coding: utf-8 -*-
"""An assigned admin with none of the active containers is told that, not "none configured".

THE FINDING (stage 4 review before v3.1.0, section 01 pass 4 F6): Restart All
and Stop All narrow the active containers to the ones assigned to the
pressing admin. When that left nothing, the admin was told "❌ No active
servers configured." - although there are active containers, just none of
theirs. The stack restart said "**G** has no active containers any more"
about a group full of them.

THE CONTRACT: when the assignment is what emptied the list, the answer says
"None of the active containers is assigned to you."; "No active servers
configured" stays for when there really are none.

HOW THIS TEST CAN FAIL: the wrong reason again, in any of the three.

COUNTER-CHECK (2026-09-29): the assignment cases red before the change;
the no-servers case green before and after.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.admin_overview as ao
import cogs.stack_restart as sr

NOT_ASSIGNED = "None of the active containers is assigned to you."


def _press(monkeypatch, button, servers, assigned):
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: SimpleNamespace(is_enabled=lambda: False))
    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))

    async def _admin(uid):
        return True
    monkeypatch.setattr(ao, "get_admin_service", lambda: SimpleNamespace(
        is_user_admin_async=_admin,
        controllable=lambda uid, items: [s for s in items if s["docker_name"] in assigned]))
    monkeypatch.setattr(ao, "_", lambda text: text)
    monkeypatch.setattr(sr, "_", lambda text: text)
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.user.id = 4711
    return inter


def _said(inter):
    return " ".join(str(c.args[0]) for c in inter.followup.send.await_args_list if c.args)


@pytest.mark.parametrize("cls", [ao.ConfirmRestartAllButton, ao.ConfirmStopAllButton])
async def test_the_bulk_buttons_name_the_assignment(monkeypatch, cls):
    inter = _press(monkeypatch, cls, [{"docker_name": "valheim", "active": True}], {"other"})
    await cls(SimpleNamespace(_bulk_operation_in_progress=False), 300).callback(inter)
    assert NOT_ASSIGNED in _said(inter), _said(inter)


@pytest.mark.parametrize("cls", [ao.ConfirmRestartAllButton, ao.ConfirmStopAllButton])
async def test_no_servers_is_still_no_servers(monkeypatch, cls):
    inter = _press(monkeypatch, cls, [], {"other"})
    await cls(SimpleNamespace(_bulk_operation_in_progress=False), 300).callback(inter)
    assert "No active servers configured." in _said(inter), _said(inter)


async def test_the_stack_restart_names_the_assignment(monkeypatch):
    inter = _press(monkeypatch, sr.ConfirmRestartStackButton, [], {"other"})
    monkeypatch.setattr(sr, "_servers_of", lambda stack: (
        [{"docker_name": "valheim", "active": True}], []))
    await sr.ConfirmRestartStackButton(SimpleNamespace(_bulk_operation_in_progress=False),
                                       300, "G").callback(inter)
    assert NOT_ASSIGNED in _said(inter), _said(inter)
