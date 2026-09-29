# -*- coding: utf-8 -*-
"""A press on 🛠️ does not write a line per container into the log.

THE FINDING (stage 4 review before v3.1.0, section 03 pass 4 F4): review E37
lowered the per-container log loops of the admin dropdown to DEBUG ("fourteen
INFO lines for one click"), but the button in front of it kept two of its
own: every press wrote 2 + 2N INFO lines, one per container before and after
sorting.

THE CONTRACT: the per-container lines are DEBUG.

HOW THIS TEST CAN FAIL: a container's name appears in an INFO record again.

COUNTER-CHECK (2026-09-29): red before the change (14 records for 7).
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cogs.admin_ui as admin_ui


async def test_seven_containers_leave_no_info_line_each(monkeypatch, caplog):
    entries = [{"display": f"Server-{n}", "order": n, "docker_name": f"s{n}"} for n in range(7)]
    monkeypatch.setattr(admin_ui, "controllable_entries", lambda servers: [dict(e) for e in entries])
    monkeypatch.setattr(admin_ui, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: []))
    monkeypatch.setattr("services.admin.admin_service.get_admin_service",
                        lambda: SimpleNamespace(is_user_admin=lambda uid: True))
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: SimpleNamespace(is_enabled=lambda: False))
    monkeypatch.setattr(admin_ui, "AdminContainerSelectView", MagicMock())
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.user.id = 4711
    inter.channel.id = 300

    button = admin_ui.AdminButton.__new__(admin_ui.AdminButton)
    button.cog = SimpleNamespace()
    button.channel_id = 300
    with caplog.at_level(logging.INFO):
        await button.callback(inter)

    noisy = [r.getMessage() for r in caplog.records
             if r.levelno >= logging.INFO and "Server-" in r.getMessage()]
    assert not noisy, f"{len(noisy)} INFO lines for one press: {noisy[:3]}"
