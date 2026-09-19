# -*- coding: utf-8 -*-
"""The toggle button tells the user when the configuration could not be loaded.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review pass 1, section 02 F4, re-checked 2026-09-19):
``ToggleButton.callback`` defers the interaction first and, if
``load_config()`` then returns nothing, answers with
``interaction.response.send_message`` - a second response to an interaction
that is already answered. py-cord raises ``InteractionResponded``, the
surrounding handler logs it, and the user sees nothing at all: the panel
just does not react. After a defer the answer has to go through
``followup``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ToggleButton


def _press(monkeypatch, config):
    spam = MagicMock()
    spam.is_enabled.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    monkeypatch.setattr(cui, "load_config", lambda: config)
    cog = MagicMock()
    cog.expanded_states = {}
    cog.pending_actions = {}
    button = ToggleButton(cog, {"docker_name": "vrising", "name": "V-Rising"},
                          is_running=True, row=0)
    interaction = MagicMock()
    interaction.user.id = 4711
    interaction.channel.id = 99
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.message = MagicMock()
    interaction.message.edit = AsyncMock()
    asyncio.run(button.callback(interaction))
    return interaction


def test_a_config_failure_reaches_the_user(monkeypatch):
    interaction = _press(monkeypatch, config={})

    interaction.response.defer.assert_awaited()
    assert interaction.followup.send.await_count == 1, (
        "after the defer the message must go through followup - "
        f"response.send_message was used {interaction.response.send_message.await_count} time(s), "
        "which py-cord refuses for an interaction that is already answered"
    )
