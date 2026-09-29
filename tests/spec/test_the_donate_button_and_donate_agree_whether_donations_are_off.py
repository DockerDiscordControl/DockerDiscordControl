# -*- coding: utf-8 -*-
"""The Mechonate button and /donate agree on whether donations are off.

THE FINDING (stage 4 review before v3.1.0, section 05 pass 3 F3 + pass 4
F8): /donate and the /ss mech section ask is_donations_disabled(), which
requires the stored premium key to VALIDATE. The Mechonate button called any
non-empty donation_disable_key "off". With a stored key that does not
validate (a migration copies it unchecked, a hand edit, a key retired in an
update), /donate showed the panel while the button said "Premium Features
Active".

THE CONTRACT: the button asks is_donations_disabled() - one state, one
answer.

HOW THIS TEST CAN FAIL: the button decides by the key's mere presence again.

COUNTER-CHECK (2026-09-29): the invalid-key case red before the change; the
valid-key case green before and after.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.slash_commands import SlashCommandsMixin


@pytest.mark.parametrize("disabled", [False, True])
async def test_the_button_says_what_is_donations_disabled_says(monkeypatch, disabled):
    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled", lambda: disabled)
    monkeypatch.setattr("services.config.config_service.get_config_service",
                        lambda: SimpleNamespace(get_config=lambda: {"donation_disable_key": "NOT-A-VALID-KEY"}))
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    cog = MagicMock()

    await SlashCommandsMixin._handle_donate_interaction(cog, interaction)

    title = interaction.response.send_message.await_args.kwargs["embed"].title
    assert ("Premium" in title) is disabled, f"is_donations_disabled() says {disabled}, the button: {title}"
