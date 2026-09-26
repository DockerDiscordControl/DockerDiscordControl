# -*- coding: utf-8 -*-
"""The 🔧 shows only where the watchdog looks, and a group can be paused too.

THE OPERATOR (2026-09-27), with screenshots of a container's and a group's
admin panel:

* "Do we show the maintenance button only when the watchdog is active? That
  would make sense." - a pause means "watchdog, leave this alone"; on a
  container no rule watches it does nothing, and the button promised
  otherwise.
* "I should be able to put groups into maintenance as well, right?" - a
  group's panel had no 🔧, so pausing the seven containers of a game server
  meant seven panels.

THE CONTRACT: a container's panel carries 🔧 when auto-actions are on and an
enabled container-state rule listens to that container - or when it is paused
right now, so the pause can still be ended. A group's panel carries 🔧 when
any member qualifies; pressing it pauses (and ends) every member the admin
may control, and names the ones skipped.

COUNTER-CHECK (2026-09-27): red before on the unwatched container (it had a
🔧), on the group panel (it had none) and on the group pause.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation import maintenance


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _watch(monkeypatch, *names):
    monkeypatch.setattr(maintenance, "watched", lambda container: container in names)


def _members(monkeypatch, members):
    import services.config.group_service as groups

    service = MagicMock()
    service.members_of.return_value = SimpleNamespace(exists=True, containers=list(members), missing=[])
    service.find.return_value = SimpleNamespace(name="Icaruse", containers=list(members))
    monkeypatch.setattr(groups, "get_group_service", lambda: service)


def _wrench(config):
    from cogs.group_control import admin_control_view
    from cogs.watchdog_maintenance import ContainerMaintenanceButton

    view = admin_control_view(MagicMock(), config, is_running=True)
    return next((i for i in view.children if isinstance(i, ContainerMaintenanceButton)), None)


ICARUS = {"docker_name": "Icarus", "name": "Icarus", "allowed_actions": ["status", "stop", "restart"]}
GROUP = {"docker_name": "group:Icaruse", "name": "Icaruse", "allowed_actions": ["start", "stop", "restart"]}


@pytest.mark.asyncio
async def test_no_wrench_where_no_rule_watches(monkeypatch):
    _watch(monkeypatch)
    assert _wrench(ICARUS) is None, "a 🔧 on a container the watchdog does not look at"


@pytest.mark.asyncio
async def test_a_wrench_where_a_rule_watches(monkeypatch):
    _watch(monkeypatch, "Icarus")
    assert _wrench(ICARUS) is not None


@pytest.mark.asyncio
async def test_a_paused_container_keeps_its_wrench_to_end_the_pause(monkeypatch):
    _watch(monkeypatch)
    maintenance.pause("Icarus", 60)
    assert _wrench(ICARUS) is not None


@pytest.mark.asyncio
async def test_a_group_with_a_watched_member_has_a_wrench(monkeypatch):
    _watch(monkeypatch, "Icarus2")
    _members(monkeypatch, ["Icarus", "Icarus2"])
    wrench = _wrench(GROUP)
    assert wrench is not None, "no 🔧 on the group panel"
    assert wrench.containers == ["Icarus", "Icarus2"]


@pytest.mark.asyncio
async def test_a_group_nobody_watches_has_none(monkeypatch):
    _watch(monkeypatch)
    _members(monkeypatch, ["Icarus", "Icarus2"])
    assert _wrench(GROUP) is None


def _admin(monkeypatch, allowed):
    import cogs.admin_overview as overview
    import services.admin.admin_service as admin_module

    # The spam brake has its own test (test_spam_settings_are_checked_by_the_server);
    # here one user presses twice in a row on purpose.
    monkeypatch.setattr(overview, "_admin_button_braked", AsyncMock(return_value=False))

    monkeypatch.setattr(admin_module, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=AsyncMock(return_value=True),
                                                may_control=lambda _uid, name: name in allowed))


async def _press(wrench, label):
    sent = AsyncMock()
    await wrench.callback(SimpleNamespace(user=SimpleNamespace(id=1),
                                          response=SimpleNamespace(send_message=sent)))
    view = sent.await_args.kwargs["view"]
    button = next(item for item in view.children if getattr(item, "label", None) == label)
    reply = SimpleNamespace(user=SimpleNamespace(id=1, __str__=lambda self: "op"),
                            response=SimpleNamespace(send_message=AsyncMock()))
    await button.callback(reply)
    return str(reply.response.send_message.await_args)


@pytest.mark.asyncio
async def test_the_group_wrench_pauses_every_member_the_admin_may_control(monkeypatch):
    from cogs.watchdog_maintenance import ContainerMaintenanceButton

    _admin(monkeypatch, {"Icarus", "Icarus2"})
    await _press(ContainerMaintenanceButton(["Icarus", "Icarus2"], label="Icaruse"), "1 h")
    assert maintenance.is_paused("Icarus") and maintenance.is_paused("Icarus2")

    await _press(ContainerMaintenanceButton(["Icarus", "Icarus2"], label="Icaruse"), "End maintenance")
    assert not maintenance.is_paused("Icarus") and not maintenance.is_paused("Icarus2")


@pytest.mark.asyncio
async def test_a_scoped_admin_pauses_only_their_members(monkeypatch):
    from cogs.watchdog_maintenance import ContainerMaintenanceButton

    _admin(monkeypatch, {"Icarus"})
    answer = await _press(ContainerMaintenanceButton(["Icarus", "Icarus2"], label="Icaruse"), "1 h")
    assert maintenance.is_paused("Icarus") and not maintenance.is_paused("Icarus2")
    assert "Icarus2" in answer, "the skipped member was not named"


def test_watched_asks_the_rules(monkeypatch):
    """The helper itself: auto-actions on, an enabled container-state rule."""
    import services.automation.auto_action_config_service as aac

    def rule(containers, enabled=True, kind="container_state"):
        return SimpleNamespace(enabled=enabled, trigger=SimpleNamespace(type=kind, containers=containers))

    service = MagicMock()
    service.get_global_settings.return_value = {"enabled": True}
    service.get_rules.return_value = [rule(["Icarus"]), rule([], enabled=False), rule([], kind="message")]
    monkeypatch.setattr(aac, "get_auto_action_config_service", lambda: service)

    assert maintenance.watched("Icarus")
    assert not maintenance.watched("Valheim")
    service.get_global_settings.return_value = {"enabled": False}
    assert not maintenance.watched("Icarus")
