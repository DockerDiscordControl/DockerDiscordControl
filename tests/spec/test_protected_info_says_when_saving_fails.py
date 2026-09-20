# -*- coding: utf-8 -*-
"""A protected-info save that hits the file system still answers the user.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 07 F2, re-checked 2026-09-20):
``ProtectedInfoModal.callback`` catches RuntimeError, the two asyncio errors
and three discord errors - but not IOError/OSError/PermissionError, and not
the docker errors. The very same call in the sibling modal
(``SimplifiedContainerInfoModal.callback``, a hundred lines up) catches all
of them and answers "check permissions on config directory". A permission
problem on ``config/`` is not a theoretical case here: the directory is
deliberately locked down, and the project notes name it as a recurring
failure. The user then sees Discord's own "The application did not respond"
and has no idea whether the secret was saved.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.enhanced_info_modal_simple import ProtectedInfoModal


def _field(value):
    return SimpleNamespace(value=value)


def _modal(save_raises=None):
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(
        success=True,
        data=SimpleNamespace(to_dict=lambda: {"enabled": True, "show_ip": False,
                                              "custom_ip": "", "custom_port": "",
                                              "custom_text": ""}))
    if save_raises is not None:
        info_service.save_container_info.side_effect = save_raises
    else:
        info_service.save_container_info.return_value = SimpleNamespace(success=True, error=None)

    modal = ProtectedInfoModal.__new__(ProtectedInfoModal)
    modal.container_name = "vrising"
    modal.display_name = "V-Rising"
    modal.cog = MagicMock()
    modal.info_service = info_service
    modal.protected_enabled = _field("x")
    modal.protected_content = _field("the server password is hunter2")
    modal.protected_password = _field("open-sesame")
    return modal


def _interaction():
    interaction = MagicMock()
    interaction.user = SimpleNamespace(id=4711, name="tester", __str__=lambda self: "tester")
    interaction.guild = SimpleNamespace(name="guild")
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = False
    interaction.followup.send = AsyncMock()
    return interaction


def _answer(interaction):
    calls = (interaction.response.send_message.await_args_list
             + interaction.followup.send.await_args_list)
    return [call.args[0] for call in calls if call.args]


def test_a_working_save_answers(monkeypatch):
    """Premise: with a working save the user gets an answer at all."""
    interaction = _interaction()
    asyncio.run(_modal().callback(interaction))
    assert interaction.response.send_message.await_count == 1


@pytest.mark.parametrize("error", [PermissionError("config is read-only"),
                                   OSError("no space left on device")])
def test_a_file_system_error_is_answered(error):
    interaction = _interaction()

    asyncio.run(_modal(save_raises=error).callback(interaction))

    answers = _answer(interaction)
    assert answers, "the save failed and the user was told nothing at all"
    assert "❌" in answers[0], answers


def test_the_secret_is_not_in_the_answer():
    """Counter-check: the error message must not carry the content back out."""
    interaction = _interaction()

    asyncio.run(_modal(save_raises=PermissionError("config is read-only")).callback(interaction))

    for answer in _answer(interaction):
        assert "hunter2" not in answer and "open-sesame" not in answer, answer
