# -*- coding: utf-8 -*-
# @covers Z5
"""Z5 - creating a scheduled task needs the channel's permission, like deleting one.

THE FINDING (stage 4 review, stage B, section 09 F2, re-checked 2026-09-20):
``CreateTaskButton.callback`` re-checks which ACTIONS the container allows,
but never the channel's permission - not at the click, not at creation. Its
twin, ``ContainerTaskDeleteButton``, checks ``schedule`` since 4379ea8. The
same thing - a scheduled start/stop/restart of a container - therefore
needed a permission on one path and none on the other, which is the finding
of 2026-09-17 on the other side. And the view that carries this button lives
up to ~890 s, so a panel opened while the channel still had the permission
keeps creating tasks after it is revoked: a permission living in a message,
which the operator ruled out on 2026-09-16.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.status_info_integration as sii
from cogs.status_info_integration import CreateTaskButton

CHANNEL = 736_195_284


class _Created(Exception):
    """Tripwire: raised as soon as a task would be written."""


def _config(schedule):
    return {"channel_permissions": {str(CHANNEL): {"commands": {"schedule": schedule,
                                                                "control": schedule}}}}


def _press(monkeypatch, *, schedule, admin=False):
    monkeypatch.setattr(sii, "load_config", lambda: _config(schedule))
    monkeypatch.setattr("services.config.config_service.load_config", lambda: _config(schedule))
    monkeypatch.setattr("cogs.control_helpers.load_config", lambda: _config(schedule))
    admin_service = MagicMock()
    admin_service.is_user_admin.return_value = admin
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: admin_service)
    monkeypatch.setattr(sii, "_get_allowed_task_actions", lambda _name: ["start", "stop", "restart"])

    def _tripwire(*_a, **_k):
        raise _Created()

    monkeypatch.setattr("services.scheduling.scheduler.add_task", _tripwire)

    button = CreateTaskButton.__new__(CreateTaskButton)
    button.cog = SimpleNamespace()
    button.container_name = "vrising"
    button._view = SimpleNamespace(selected_cycle="daily", selected_action="restart",
                                   selected_time="04:00", selected_day=None,
                                   container_name="vrising")
    type(button).view = property(lambda self: self._view)
    interaction = MagicMock()
    interaction.channel_id = CHANNEL
    interaction.channel = SimpleNamespace(id=CHANNEL)
    interaction.user.id = 4711
    interaction.user.name = "Somebody"
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return button, interaction


def _sent(interaction):
    return " ".join(str(a) for call in interaction.followup.send.await_args_list
                    for a in call.args)


def test_without_the_permission_no_task_is_created(monkeypatch):
    button, interaction = _press(monkeypatch, schedule=False)

    asyncio.run(button.callback(interaction))      # must not reach add_task

    assert "not allowed in this channel" in _sent(interaction).lower(), (
        f"the task was created in a channel without the 'schedule' permission; "
        f"the user was told: {_sent(interaction)!r}"
    )


def test_with_the_permission_the_task_is_created(monkeypatch):
    """Counter-check: otherwise 'never create' would pass the test above."""
    button, interaction = _press(monkeypatch, schedule=True)

    with pytest.raises(_Created):
        asyncio.run(button.callback(interaction))


def test_a_registered_admin_may_create_it(monkeypatch):
    """SPEC.md B2: the admin list counts where the channel alone permits nothing."""
    button, interaction = _press(monkeypatch, schedule=False, admin=True)

    with pytest.raises(_Created):
        asyncio.run(button.callback(interaction))
