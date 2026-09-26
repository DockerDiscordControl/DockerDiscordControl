# -*- coding: utf-8 -*-
"""An admin assigned to some containers acts on those only - everywhere.

THE FINDING (audit 2026-09-26) and THE OPERATOR'S DECISION the same day
("enforce the assignment everywhere"). SPEC B2 lets an admin be assigned to
some containers. The single-container controls honoured it; four paths did
not:

  * /addadmin in a status channel: a scoped admin added an UNSCOPED second
    account (add_admin_user writes no assignment, and none means "all");
  * Restart All / Stop All: every active container, whatever the assignment;
  * the stack restart: every member of the group or stack;
  * watchdog maintenance: any container.

THE CONTRACT: only an unscoped admin may add admins (outside control
channels, where B1 - the channel - decides as before); the bulk actions and
the stack restart act on the admin's containers only; maintenance needs the
container to be the admin's.

COUNTER-CHECK (2026-09-26): red before the fix - the scoped admin stopped
both containers, restarted both stack members, paused a foreign container,
and was offered /addadmin.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.admin.admin_service import AdminService

SCOPED, FREE = "111111111111111111", "222222222222222222"


@pytest.fixture
def admins(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    (tmp_path / "admins.json").write_text(json.dumps({
        "discord_admin_users": [SCOPED, FREE],
        "admin_containers": {SCOPED: ["valheim"]}}))
    service = AdminService.__new__(AdminService)
    AdminService.__init__(service)
    return service


def test_only_an_unscoped_admin_may_make_admins(admins):
    assert admins.is_unscoped_admin(FREE) is True
    assert admins.is_unscoped_admin(SCOPED) is False


def test_the_bulk_list_is_the_admins_own(admins):
    servers = [{"docker_name": "valheim"}, {"docker_name": "plex"}]

    assert [s["docker_name"] for s in admins.controllable(SCOPED, servers)] == ["valheim"]
    assert len(admins.controllable(FREE, servers)) == 2


@pytest.mark.asyncio
async def test_stop_all_stops_only_the_assigned_container(admins, monkeypatch):
    from cogs import admin_overview as ao
    from cogs.admin_overview import ConfirmStopAllButton

    acted = []

    async def _action(name, action):
        acted.append(name)
        return True

    monkeypatch.setattr("services.docker_service.docker_action_service.docker_action_service_first", _action)
    monkeypatch.setattr(ao, "get_admin_service", lambda: admins)
    servers = [{"docker_name": n, "name": n, "active": True, "allowed_actions": ["stop"]}
               for n in ("valheim", "plex")]
    monkeypatch.setattr(ao, "get_server_config_service", lambda: SimpleNamespace(get_all_servers=lambda: servers))
    from services.docker_status.models import ContainerStatusResult

    monkeypatch.setattr(ao, "get_status_cache_service", lambda: SimpleNamespace(get=lambda name: {
        "data": ContainerStatusResult.success_result(docker_name=name, display_name=name, is_running=True,
                                                     cpu="1%", ram="1MB", uptime="1h", details_allowed=True)}))
    button = ConfirmStopAllButton.__new__(ConfirmStopAllButton)
    button.cog = SimpleNamespace(_bulk_operation_in_progress=False)
    button.channel_id = 1
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.user.id = int(SCOPED)

    await button.callback(interaction)

    assert acted == ["valheim"], acted


def test_maintenance_needs_the_container_to_be_the_admins(admins, monkeypatch):
    import services.admin.admin_service as admin_module
    from cogs.watchdog_maintenance import _may_pause

    monkeypatch.setattr(admin_module, "get_admin_service", lambda: admins)

    assert _may_pause(SCOPED, "valheim") is True
    assert _may_pause(SCOPED, "plex") is False
    assert _may_pause(FREE, "plex") is True


def test_addadmin_asks_for_an_unscoped_admin():
    """The call site, read: the status-channel branch of /addadmin."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "cogs" / "slash_commands.py").read_text(encoding="utf-8")
    start = source.index("async def addadmin(")
    body = source[start:source.index("@commands.slash_command", start + 10)]

    assert "is_unscoped_admin(" in body
    assert "is_user_admin(ctx.author.id)" not in body
