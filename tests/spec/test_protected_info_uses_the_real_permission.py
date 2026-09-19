# -*- coding: utf-8 -*-
"""Protected container info without a password follows the real channel permission.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review pass 1, section 02 F5, re-checked 2026-09-19):
``ContainerInfoDropdown.callback`` decided whether to show protected content
that has no password with
``channel_config.get('allow_start') or channel_config.get('allow_stop')`` -
keys a channel configuration does not have (permissions live under
``commands``). The answer was therefore always False: in a control channel
the content was never shown. It failed closed, so nothing leaked - a feature
that silently did nothing.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ContainerInfoDropdown

CHANNEL = 815_493_762
SECRET = "rcon password: swordfish"


def _config(control):
    return {"channel_permissions": {str(CHANNEL): {"commands": {"control": control,
                                                                "info": True}}}}


def _dropdown(monkeypatch, control):
    servers = MagicMock()
    servers.get_server_by_docker_name.return_value = {
        "docker_name": "vrising", "display_name": "V-Rising",
        "info": {"enabled": True, "info_text": "public", "protected_enabled": True,
                 "protected_content": SECRET, "protected_password": ""},
    }
    monkeypatch.setattr(cui, "get_server_config_service", lambda: servers)
    monkeypatch.setattr(cui, "load_config", lambda: _config(control))
    monkeypatch.setattr("services.config.config_service.load_config", lambda: _config(control))
    dropdown = ContainerInfoDropdown.__new__(ContainerInfoDropdown)
    dropdown.cog = SimpleNamespace()
    dropdown.containers = ["vrising"]
    dropdown._values = ["vrising"]
    type(dropdown).values = property(lambda self: self._values)
    interaction = MagicMock()
    interaction.channel = SimpleNamespace(id=CHANNEL)
    interaction.user.id = 4711
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()
    return dropdown, interaction


def _shown(interaction):
    texts = []
    for call in interaction.response.edit_message.await_args_list:
        embed = call.kwargs.get("embed")
        if embed is not None:
            texts += [f"{f.name} {f.value}" for f in embed.fields]
        texts.append(str(call.kwargs.get("content") or ""))
    return " ".join(texts)


@pytest.mark.asyncio
async def test_a_control_channel_sees_the_protected_info(monkeypatch):
    dropdown, interaction = _dropdown(monkeypatch, control=True)

    await dropdown.callback(interaction)

    assert SECRET in _shown(interaction), (
        "the channel has the control permission, but the protected information "
        "without a password was not shown"
    )


@pytest.mark.asyncio
async def test_a_channel_without_control_does_not(monkeypatch):
    """Counter-check: the permission must still decide, not 'always show'."""
    dropdown, interaction = _dropdown(monkeypatch, control=False)

    await dropdown.callback(interaction)

    assert SECRET not in _shown(interaction)
