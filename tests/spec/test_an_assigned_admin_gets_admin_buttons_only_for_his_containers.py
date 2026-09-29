# -*- coding: utf-8 -*-
"""The info panel's admin buttons follow an admin's container assignment.

THE FINDING (stage 4 review before v3.1.0, section 02, found by both
passes, verified 2026-09-29). InfoButton decided with the UNSCOPED
_is_registered_admin whether to build ContainerInfoAdminView (edit info,
logs, tasks): an admin assigned only to "valheim" got those controls for
every container in a status channel. B2 (2026-09-21): the controls follow
the assignment - ActionButton and the task buttons were narrowed then, this
one was not.

THE CONTRACT: in a channel without 'control', the admin view is built only
for an admin who may act on THIS container. What the embed shows (the
protected part) is not decided here - that is an open operator question.

HOW THIS TEST CAN FAIL: InfoButton grants the view to any registered admin
again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


@pytest.fixture
def pressed(monkeypatch):
    import cogs.control_ui as cui
    import cogs.control_helpers as helpers
    from cogs import status_info_integration as sii

    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr("services.infrastructure.spam_protection_service.get_spam_protection_service",
                        lambda: spam)
    monkeypatch.setattr(cui, "load_config", lambda: {"x": 1})
    monkeypatch.setattr("services.admin.admin_service.get_admin_service",
                        lambda: SimpleNamespace(is_user_admin=lambda uid: True))
    monkeypatch.setattr(helpers, "_channel_has_permission", lambda *a: False)
    monkeypatch.setattr(cui, "_is_registered_admin", lambda uid: True)
    may = {"value": False}
    monkeypatch.setattr(cui, "_admin_may_control", lambda uid, name: may["value"])
    monkeypatch.setattr(cui.InfoButton, "_channel_has_info_permission", lambda self, *a: True)
    monkeypatch.setattr(sii.StatusInfoButton, "_generate_info_embed",
                        AsyncMock(return_value=discord.Embed(title="info")))

    def _press(enabled):
        info = SimpleNamespace(to_dict=lambda: {"enabled": enabled, "custom_text": "x"})
        monkeypatch.setattr("services.infrastructure.container_info_service.get_container_info_service",
                            lambda: SimpleNamespace(get_container_info=lambda n: SimpleNamespace(
                                success=True, data=info)))
        interaction = MagicMock()
        interaction.user.id = 7
        interaction.channel.id = 5
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        button = cui.InfoButton(MagicMock(), {"docker_name": "nginx", "name": "nginx"}, 0)
        asyncio.run(button.callback(interaction))
        return [c.kwargs.get("view") for c in interaction.followup.send.await_args_list]

    return _press, may


@pytest.mark.parametrize("enabled", [True, False])
def test_no_admin_view_for_somebody_elses_container(pressed, enabled):
    _press, _may = pressed

    views = _press(enabled)

    assert not any(type(v).__name__ == "ContainerInfoAdminView" for v in views), views


def test_his_own_container_gets_the_admin_view(pressed):
    """Counter-check: the assigned container keeps its controls."""
    _press, may = pressed
    may["value"] = True

    views = _press(True)

    assert any(type(v).__name__ == "ContainerInfoAdminView" for v in views), views
