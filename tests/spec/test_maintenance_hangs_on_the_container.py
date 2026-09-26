# -*- coding: utf-8 -*-
"""Maintenance is set where the container is: on its own admin panel.

THE OPERATOR (2026-09-26), with a screenshot of a container's private admin
panel (stop, restart, info, close): "we should hang the maintenance button
directly on the containers in Discord". The 🔧 of the overview asked for the
container a second time; here it is already chosen, so only the duration is.

THE CONTRACT: a container's admin panel carries 🔧 before its close button,
green while the container is paused; pressing it offers the durations for
THAT container and sets its pause. Since 2026-09-27 only where the watchdog
looks, and a group's panel has one too - both in
test_the_wrench_shows_where_the_watchdog_looks.py; here the watchdog is
taken to watch every container. The overview no longer draws a 🔧, but still registers it
so an overview posted that evening goes on answering.

COUNTER-CHECK (2026-09-26): red before the move - no 🔧 on the container
panel, and the overview drew one.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation import maintenance


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(maintenance, "watched", lambda _container: True)
    return tmp_path


def _panel(config):
    from cogs.group_control import admin_control_view

    return admin_control_view(MagicMock(), config, is_running=True)


def _wrench(view):
    from cogs.watchdog_maintenance import ContainerMaintenanceButton

    return next((item for item in view.children if isinstance(item, ContainerMaintenanceButton)), None)


@pytest.mark.asyncio
async def test_a_container_panel_carries_the_wrench_before_its_close_button():
    from cogs.ddc_ui import CloseButton

    view = _panel({"docker_name": "Icarus", "name": "Icarus", "allowed_actions": ["status", "stop", "restart"]})
    wrench = _wrench(view)

    assert wrench is not None and wrench.container == "Icarus"
    assert isinstance(view.children[-1], CloseButton)


@pytest.mark.asyncio
async def test_it_is_green_while_the_container_is_paused():
    import discord

    maintenance.pause("Icarus", 60)
    view = _panel({"docker_name": "Icarus", "name": "Icarus", "allowed_actions": ["status"]})

    assert _wrench(view).style == discord.ButtonStyle.success


@pytest.mark.asyncio
async def test_a_group_without_members_has_none():
    """A group whose members DDC does not have: nothing to pause."""
    view = _panel({"docker_name": "group:Gameserver", "name": "Gameserver", "allowed_actions": ["restart"]})

    assert _wrench(view) is None


@pytest.mark.asyncio
async def test_pressing_it_offers_the_durations_for_that_container(monkeypatch):
    import services.admin.admin_service as admin_module
    from cogs.watchdog_maintenance import ContainerMaintenanceButton

    monkeypatch.setattr(admin_module, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=AsyncMock(return_value=True),
                                          may_control=lambda _uid, _name: True))
    sent = AsyncMock()
    interaction = SimpleNamespace(user=SimpleNamespace(id=1), response=SimpleNamespace(send_message=sent))

    await ContainerMaintenanceButton("Icarus").callback(interaction)

    view = sent.await_args.kwargs["view"]
    assert view.chosen == "Icarus"
    assert not any(getattr(item, "placeholder", None) for item in view.children), "asked for the container again"
    hour = next(item for item in view.children if getattr(item, "label", None) == "1 h")
    reply = SimpleNamespace(user=SimpleNamespace(id=1, __str__=lambda self: "op"),
                            response=SimpleNamespace(send_message=AsyncMock()))
    await hour.callback(reply)
    assert maintenance.is_paused("Icarus")


@pytest.mark.asyncio
async def test_the_overview_no_longer_draws_it_but_still_answers_it():
    from cogs.admin_overview import AdminOverviewView

    drawn = AdminOverviewView(MagicMock(), 7, has_running_containers=True)
    registered = AdminOverviewView(MagicMock(), 7, has_running_containers=True, every_button=True)

    assert "admin_overview_maintenance_7" not in [b.custom_id for b in drawn.children]
    assert "admin_overview_maintenance_7" in [b.custom_id for b in registered.children]
