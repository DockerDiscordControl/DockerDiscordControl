# -*- coding: utf-8 -*-
"""The mech history button acknowledges the click, spam protection or not.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 03 F2, re-checked 2026-09-20):
in ``MechHistoryButton.callback`` the ``interaction.response.defer()`` sits
INSIDE ``if spam_service.is_enabled():`` - a comment of mine from the spam
work even says so and calls changing it "a separate decision". Everything
after it answers through ``interaction.followup``, which needs that
acknowledgement. With spam protection switched off the button therefore
fails on every press: py-cord refuses the followup, the callback's own
``except (RuntimeError, ValueError, KeyError)`` does not catch it, and the
user sees Discord's "This interaction failed".

Checked with an AST scan over cogs/control_ui.py: this is the only callback
whose defer only runs under spam protection.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.control_ui as cui
from cogs.control_ui import MechHistoryButton


def _press(monkeypatch, *, spam_enabled):
    spam = MagicMock()
    spam.is_enabled.return_value = spam_enabled
    spam.is_on_cooldown.return_value = False
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: spam)
    mech = MagicMock()
    mech.get_mech_state_service.return_value = SimpleNamespace(success=True, level=3)
    monkeypatch.setattr("services.mech.mech_service_adapter.get_mech_service",
                        lambda: mech, raising=False)
    monkeypatch.setattr(MechHistoryButton, "_show_mech_selection", AsyncMock())

    button = MechHistoryButton(MagicMock(), 99)
    interaction = MagicMock()
    interaction.user.id = 4711
    interaction.user.name = "tester"
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    asyncio.run(button.callback(interaction))
    return interaction


@pytest.mark.parametrize("spam_enabled", [True, False], ids=["spam-on", "spam-off"])
def test_the_click_is_acknowledged(monkeypatch, spam_enabled):
    interaction = _press(monkeypatch, spam_enabled=spam_enabled)

    interaction.response.defer.assert_awaited_once()
