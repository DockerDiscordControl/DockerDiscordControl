# -*- coding: utf-8 -*-
"""An action removed from a container cannot be pressed on a panel drawn before.

THE FINDING (stage 4 review before v3.1.0, section 02 pass 4 F2, verified
2026-09-29). ActionButton read allowed_actions from the server_config dict
it was built with. A panel that is not redrawn - above all the private
admin panel, whose redraw after a press reuses the same dict - still ran an
action the operator had since taken away. The channel half of Z5 moved to
press time on 2026-09-16; this half did not.

THE CONTRACT: the press asks the CURRENT configuration whether the action
is allowed; a container no longer configured is refused too.

HOW THIS TEST CAN FAIL: the button trusts the dict it was drawn with again.

It goes through ActionButton.callback up to the refusal, with the Docker
call as a spy.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


@pytest.fixture
def press(monkeypatch):
    import cogs.control_ui as control_ui

    current = {"web": {"docker_name": "web", "allowed_actions": ["status"]}}
    monkeypatch.setattr(control_ui, "load_config", lambda: {"x": 1})
    monkeypatch.setattr(control_ui, "_get_cached_channel_permission", lambda *a: True)
    monkeypatch.setattr(control_ui, "get_server_config_service", lambda: SimpleNamespace(
        get_server_by_docker_name=lambda name: current.get(name)))
    spam = SimpleNamespace(is_enabled=lambda: False)
    monkeypatch.setattr("services.infrastructure.spam_protection_service.get_spam_protection_service",
                        lambda: spam)
    acted = []
    monkeypatch.setattr(control_ui, "refused_while_busy", AsyncMock(side_effect=lambda *a: acted.append(a) or True))

    def _press(drawn_with):
        button = control_ui.ActionButton(MagicMock(pending_actions={}), drawn_with, "stop",
                                         discord.ButtonStyle.danger, "Stop", "⏹️", 0)
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.channel.id = 5
        asyncio.run(button.callback(interaction))
        return interaction, acted

    return _press, current


def test_an_action_taken_away_since_is_refused(press):
    _press, _current = press

    interaction, acted = _press({"docker_name": "web", "allowed_actions": ["stop"]})

    assert not acted, "the stop went on although 'stop' is no longer allowed"
    assert "not allowed" in interaction.followup.send.await_args.args[0]


def test_a_container_no_longer_configured_is_refused(press):
    _press, current = press
    current.clear()

    interaction, acted = _press({"docker_name": "web", "allowed_actions": ["stop"]})

    assert not acted


def test_an_allowed_action_still_goes_on(press):
    """Counter-check: with 'stop' allowed now, the press reaches the next step."""
    _press, current = press
    current["web"]["allowed_actions"] = ["stop"]

    _interaction, acted = _press({"docker_name": "web", "allowed_actions": ["stop"]})

    assert acted, "an allowed action was refused"
