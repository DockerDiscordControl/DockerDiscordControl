# -*- coding: utf-8 -*-
"""A registered admin gets the info admin view from the public ℹ️ button too.

THE FINDING (stage 4 review before v3.1.0, section 09 pass 3 F2 + pass 4 F4):
the public info button on status-only channel messages (StatusInfoButton)
decided the admin view - edit info, protected info, tasks, logs - by the
channel's control permission alone. A registered admin pressing it got the
plain info; from the admin panel's info button (control_ui.InfoButton) the
same admin got the admin view. SPEC B2: the admin list exists for the status
channels.

THE OPERATOR (2026-09-29): the admin view there too, following the admin's
container assignment - like InfoButton. What the embed SHOWS is not narrowed
(B2, "seeing is not narrowed"; Q10 of the same day): a registered admin sees
the password-less protected info, assigned or not.

HOW THIS TEST CAN FAIL: an admin gets no admin view again; an admin assigned
to other containers gets the controls for this one; a member who is no admin
gets them.

COUNTER-CHECK (2026-09-29): the first two cases were red before the change -
the admin of other containers did not even SEE the protected info - the member
case green before and after.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_helpers as helpers
import cogs.status_info_integration as sii
from cogs.status_info_integration import StatusInfoButton


class _AdminView:
    def __init__(self, *args, **kwargs):
        pass


def _press(monkeypatch, *, registered, may_control):
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    monkeypatch.setattr(sii, "load_config", lambda: {"channel_permissions": {}})
    monkeypatch.setattr(helpers, "_channel_has_permission", lambda *a, **k: False)
    monkeypatch.setattr(helpers, "_is_registered_admin", lambda user_id: registered)
    monkeypatch.setattr(helpers, "_admin_may_control", lambda user_id, name: may_control)
    monkeypatch.setattr(sii, "ContainerInfoAdminView", _AdminView)
    seen = {}

    async def _embed(self, include_protected=False):
        seen["protected"] = include_protected
        return MagicMock()
    monkeypatch.setattr(StatusInfoButton, "_generate_info_embed", _embed)

    button = StatusInfoButton.__new__(StatusInfoButton)
    button.cog = MagicMock()
    button.server_config = {"docker_name": "nginx"}
    button.info_config = {}
    button.container_name = "nginx"
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.user.id = 4711
    inter.channel_id = 300
    asyncio.run(button.callback(inter))
    view = inter.followup.send.await_args.kwargs.get("view")
    return isinstance(view, _AdminView), seen.get("protected")


def test_an_assigned_admin_gets_the_admin_view(monkeypatch):
    got_view, protected = _press(monkeypatch, registered=True, may_control=True)
    assert got_view, "a registered admin pressed the public info button and got no admin view"
    assert protected is True


def test_an_admin_of_other_containers_sees_but_gets_no_controls(monkeypatch):
    got_view, protected = _press(monkeypatch, registered=True, may_control=False)
    assert not got_view, "the controls ignored the admin's container assignment"
    assert protected is True, "seeing is not narrowed (B2): the protected info was hidden"


def test_a_member_gets_neither(monkeypatch):
    got_view, protected = _press(monkeypatch, registered=False, may_control=False)
    assert not got_view and protected is False
