# -*- coding: utf-8 -*-
# @covers Z5
"""Z5 and B2 - a registered admin may act in a channel without the right.

THE FINDING (operator's phone screenshot, 2026-09-19): in a STATUS channel
the operator - a registered admin - opened the admin panel for a container
and pressed start. The bot answered, in German, "this action is not allowed
in this channel".

B2, confirmed on 2026-09-16: the global admin list (``/addadmin``,
``admins.json``) exists precisely so that admins may act in status
channels, where channel membership alone permits nothing. The operator
restated it with this report: as a registered admin they should have that
right.

HOW IT BROKE - MY OWN REGRESSION: before 2026-09-16 the admin panel worked
only through its message title: "Admin Control" in the embed title
short-circuited the channel check. The Z5 fix (control_ui.py:304, then
:1019/:1072 on 2026-09-17) removed the title as a permission - rightly, a
right must not live in a message - but replaced it with NOTHING. Since then
only the channel counted, and B2 was dead on every path that fix touched:
start/stop/restart, the info admin view (edit, task management), and the
task delete button that the 2026-09-17 fix gave a 'schedule' check.

THE RULE NOW: the channel's CURRENT permission, or the pressing user being
in the CURRENT admin list. Both come from the configuration at the moment
of the press; nothing is read from the message. So the operator's decision
of 2026-09-16 still holds: an old "Admin Control" title grants nothing to a
non-admin (checked below).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ActionButton, InfoButton, TaskDeleteButton

ADMIN_ID = 4711


class _Passed(Exception):
    """Tripwire: raised once the permission check has been passed."""


def _interaction(*, title=None):
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = ADMIN_ID
    inter.user.name = "Operator"
    inter.channel.id = 300
    inter.channel_id = 300
    inter.message = None if title is None else SimpleNamespace(
        embeds=[SimpleNamespace(title=title)])
    return inter


def _tripwire(*_a, **_k):
    raise _Passed()


@pytest.fixture
def status_channel(monkeypatch):
    """A status channel: 'info' yes, 'control' and 'schedule' no."""
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    config = {"servers": [], "channel_permissions": {
        "300": {"commands": {"info": True, "control": False, "schedule": False}}}}
    monkeypatch.setattr(cui, "load_config", lambda: config)
    monkeypatch.setattr("cogs.status_info_integration.load_config", lambda: config)
    monkeypatch.setattr("cogs.control_helpers.load_config", lambda: config)
    admin = MagicMock()
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: admin)
    return admin


def _action_button():
    b = ActionButton.__new__(ActionButton)
    b.cog = SimpleNamespace(pending_actions={})
    b.action = "start"
    b.server_config = {"docker_name": "vrising", "display_name": "V-Rising",
                       "allowed_actions": ["start", "stop", "restart"]}
    b.docker_name = "vrising"
    b.display_name = "V-Rising"
    return b


async def test_an_admin_may_start_a_container_in_a_status_channel(status_channel, monkeypatch):
    """THE FINDING: the admin is refused in the status channel."""
    status_channel.is_user_admin.return_value = True
    monkeypatch.setattr(cui, "_get_pending_embed", _tripwire)

    with pytest.raises(_Passed):
        await _action_button().callback(_interaction(title="🛠️ Admin Control: V-Rising"))


async def test_a_non_admin_is_refused_even_with_the_admin_title(status_channel, monkeypatch):
    """The other direction: the admin list opens the gate, the title does not."""
    status_channel.is_user_admin.return_value = False
    monkeypatch.setattr(cui, "_get_pending_embed", _tripwire)
    button = _action_button()
    inter = _interaction(title="🛠️ Admin Control: V-Rising")

    await button.callback(inter)

    assert button.cog.pending_actions == {}
    sent = " ".join(str(a) for c in inter.followup.send.await_args_list for a in c.args)
    assert "not allowed in this channel" in sent, sent


def _info_button():
    b = InfoButton.__new__(InfoButton)
    b.cog = SimpleNamespace()
    b.server_config = {"docker_name": "vrising", "display_name": "V-Rising"}
    b.docker_name = "vrising"
    b.display_name = "V-Rising"
    return b


@pytest.mark.parametrize("info_enabled", [True, False], ids=["info-set", "no-info-yet"])
async def test_an_admin_gets_the_info_admin_view(status_channel, monkeypatch, info_enabled):
    """Both branches of InfoButton.callback that decide on ContainerInfoAdminView."""
    status_channel.is_user_admin.return_value = True
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(
        success=True,
        data=SimpleNamespace(to_dict=lambda: {"enabled": info_enabled, "info_text": "x"}))
    monkeypatch.setattr(
        "services.infrastructure.container_info_service.get_container_info_service",
        lambda: info_service)
    monkeypatch.setattr("cogs.status_info_integration.ContainerInfoAdminView", _tripwire)
    monkeypatch.setattr("cogs.status_info_integration.StatusInfoButton._generate_info_embed",
                        AsyncMock(return_value=MagicMock()))

    with pytest.raises(_Passed):
        await _info_button().callback(_interaction())


async def test_an_admin_may_delete_a_task_via_the_info_view(status_channel, monkeypatch):
    status_channel.is_user_admin.return_value = True
    from cogs.status_info_integration import ContainerTaskDeleteButton
    button = ContainerTaskDeleteButton.__new__(ContainerTaskDeleteButton)
    button.cog = SimpleNamespace()
    button.task_id = "t1"
    button.description = "Daily restart"
    monkeypatch.setattr("services.scheduling.scheduler.find_task_by_id", lambda _id: MagicMock())
    monkeypatch.setattr("services.scheduling.scheduler.delete_task", _tripwire)

    with pytest.raises(_Passed):
        await button.callback(_interaction())


async def test_an_admin_may_delete_a_task_via_the_control_panel(status_channel, monkeypatch):
    """The twin delete button - same action, same rule."""
    status_channel.is_user_admin.return_value = True
    button = TaskDeleteButton.__new__(TaskDeleteButton)
    button.cog = SimpleNamespace()
    button.task_id = "t1"
    button.task_description = "Daily restart"
    monkeypatch.setattr("services.scheduling.scheduler.delete_task", _tripwire)

    with pytest.raises(_Passed):
        await button.callback(_interaction())
