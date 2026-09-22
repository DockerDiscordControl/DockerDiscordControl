# -*- coding: utf-8 -*-
"""A password that protects on one path and not on another protects nothing.

THE FINDING (review F3, operator's question 2026-09-21): the same protected
container information is reachable on three paths, and they disagreed about
what the password means.

    admin dropdown (control_ui.py:1780)  password set -> asks for it, in EVERY
                                         channel. Correct.
    info embed (_generate_info_embed)    password ignored. `include_protected`
                                         is "control channel OR registered
                                         admin", and the content went straight
                                         into the embed.
    edit button (ProtectedInfoEditButton) opens a modal PRE-FILLED with the
                                         content and the password, both in
                                         clear text.

Measured, not assumed: a probe with `protected_password` set and
`include_protected=True` put the secret into the embed.

DECIDED BY THE OPERATOR: **the password always applies.** If one is set, the
content is not handed out without it - not to a control channel and not to an
admin. Whoever knows the password gets it through the door that asks.

The edit button is a different matter and is NOT settled by this commit: an
editor must be able to change a password nobody remembers any more, and the
web panel shows the same fields to whoever logs in there. What this commit
does fix about it is who may open it at all - it carried no check of its own,
only the one that built the view around it, and that check does not know
about container assignments.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.infrastructure.container_info_service as info_service_module
from cogs.status_info_integration import StatusInfoButton

SECRET = "SERVERPASSWORT-GEHEIM"


def _info(*, password):
    return {"enabled": True, "show_ip": False, "custom_text": "",
            "protected_enabled": True,
            "protected_password": password,
            "protected_content": SECRET}


def _button(info):
    button = StatusInfoButton.__new__(StatusInfoButton)
    button.cog = SimpleNamespace()
    button.server_config = {"docker_name": "enshrouded", "name": "Enshrouded"}
    button.container_name = "enshrouded"
    button.info_config = dict(info)
    return button


@pytest.fixture
def container_info(monkeypatch):
    """The info the embed re-reads. Patched at the SERVICE's own module.

    The method imports it locally, so patching cogs.status_info_integration
    does nothing - the first version of this probe did exactly that and
    reported "no secret" about code that hands it out.
    """
    state = {"info": _info(password="hunter2")}
    monkeypatch.setattr(info_service_module, "get_container_info_service",
                        lambda: SimpleNamespace(
                            get_container_info=lambda name: SimpleNamespace(
                                success=True,
                                data=SimpleNamespace(to_dict=lambda: dict(state["info"])))))
    return state


def _text(embed):
    return (embed.description or "") + " ".join(
        str(field.value) for field in getattr(embed, "fields", []))


async def test_a_set_password_keeps_the_secret_out_of_the_embed(container_info):
    """The finding: control permission is not the password."""
    embed = await _button(container_info["info"])._generate_info_embed(include_protected=True)

    assert SECRET not in _text(embed), (
        "the protected content went into the embed although a password is set - "
        "the dropdown path asks for that password in every channel"
    )


async def test_without_a_password_it_is_still_shown(container_info):
    """The counter-case, and the behaviour the control channel relies on.

    'Protected' without a password is protected by nothing; it is the
    additional-information field, and a control channel has always shown it.
    """
    container_info["info"] = _info(password="")

    embed = await _button(container_info["info"])._generate_info_embed(include_protected=True)

    assert SECRET in _text(embed)


@pytest.mark.parametrize("password", ["hunter2", ""])
async def test_without_control_nothing_is_shown_either_way(container_info, password):
    """A pin: include_protected=False keeps it out regardless."""
    container_info["info"] = _info(password=password)

    embed = await _button(container_info["info"])._generate_info_embed(include_protected=False)

    assert SECRET not in _text(embed)


# --------------------------------------------------------------------------
# Who may open the editor at all. The modal it opens is pre-filled with the
# content AND the password in clear text, so opening it is reading them.
# --------------------------------------------------------------------------

MINE, THEIRS = "enshrouded", "valheim"


def _edit_button(container):
    from cogs.status_info_integration import ProtectedInfoEditButton
    button = ProtectedInfoEditButton.__new__(ProtectedInfoEditButton)
    button.cog = SimpleNamespace()
    button.container_name = container
    button.server_config = {"docker_name": container, "name": container}
    button.info_config = {}
    return button


def _edit_interaction():
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.response.send_modal = AsyncMock()
    inter.user.id = 4711
    inter.channel_id = 300
    inter.channel = SimpleNamespace(id=300)
    return inter


@pytest.fixture
def status_channel(monkeypatch):
    """A status channel plus an admin assigned to MINE only."""
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    config = {"servers": [], "channel_permissions": {
        "300": {"commands": {"info": True, "control": False}}}}
    monkeypatch.setattr("cogs.status_info_integration.load_config", lambda: config)
    monkeypatch.setattr("services.config.config_service.load_config", lambda: config)
    monkeypatch.setattr("cogs.control_helpers.load_config", lambda: config)

    service = MagicMock()
    service.is_user_admin.side_effect = lambda user_id, **kw: str(user_id) == "4711"
    service.may_control.side_effect = (
        lambda user_id, docker_name, **kw: str(user_id) == "4711" and docker_name == MINE)
    monkeypatch.setattr("services.admin.admin_service.get_admin_service", lambda: service)
    return service


async def test_he_may_edit_the_protected_info_of_his_own_container(status_channel):
    inter = _edit_interaction()

    await _edit_button(MINE).callback(inter)

    inter.response.send_modal.assert_awaited(), "the editor was refused for his own container"


async def test_he_may_not_edit_somebody_elses(status_channel):
    inter = _edit_interaction()

    await _edit_button(THEIRS).callback(inter)

    inter.response.send_modal.assert_not_awaited()
    sent = " ".join(str(a) for c in inter.response.send_message.await_args_list for a in c.args)
    assert "not allowed" in sent.lower(), sent
