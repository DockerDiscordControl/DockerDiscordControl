# -*- coding: utf-8 -*-
"""The public Broadcast Donation button asks the spam service like the rest.

THE FINDING (independent review of the donation path, 2026-09-23): `/donate`
posts its view NON-ephemerally and leaves it live for 890 seconds, so everyone
in the channel sees the "📢 Broadcast Donation" button and everyone can press
it. `broadcast_clicked` opened the modal straight away: no cooldown, no
per-minute limit, nothing.

Every other mech button goes through `_mech_button_braked`
(control_ui.py) - the sliders the operator sets in the panel exist for exactly
this. The donate SLIDER (`mech_donate`, 10 s by default) braked the Power/
Donate button and the private one, and did not reach this one.

What the gap costs: each press opens a modal that books a real DonationAdded
event, with `interaction.id` as the idempotency key - a new one every press, so
the ledger's own protection never bites. The event log is append-only and
replayed on every rebuild, and a wrong entry can only be taken back one seq at
a time in the panel. The embed then goes to EVERY channel in
channel_permissions, including channels the presser cannot see.

This test is about the missing brake, which is a plain oversight. WHO may
record a donation is a separate question, and the operator's: DDC's donations
are an honour system by design.

HOW THIS TEST CAN FAIL: it presses the button twice with the real spam service
behind it. If the second press still opens the modal, the brake is missing and
the test is red.

COUNTER-CHECK (2026-09-23): red before - two modals, and the service was never
asked. The other tests keep the button working: the first press opens the
modal, and with spam protection switched off nothing brakes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.donation_ui import DonationView
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 7711
CHANNEL = 4242

# The bucket the brake must land in. Not "donation_broadcast": get_button_cooldown
# derives the slider only from a name that starts with "mech_", so an ID of its
# own would brake by the 5-second fallback and leave the operator's donate
# slider dead - the very mistake test_unbraked_mech_buttons_brake.py names.
EXPECTED_KEY = f"mech_donate_{CHANNEL}"


class _Recorder:
    """Passes through to the REAL service and records what was asked."""

    def __init__(self, real):
        self._real = real
        self.asked = []
        self.recorded = []

    def is_on_cooldown(self, user_id, action_type):
        self.asked.append((user_id, action_type))
        return self._real.is_on_cooldown(user_id, action_type)

    def add_user_cooldown(self, user_id, action_type):
        self.recorded.append((user_id, action_type))
        return self._real.add_user_cooldown(user_id, action_type)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _interaction():
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.user.name = "someone_in_the_channel"
    interaction.channel.id = CHANNEL
    interaction.channel_id = CHANNEL
    interaction.response.send_modal = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup.send = AsyncMock()
    return interaction


async def _press(view, service):
    interaction = _interaction()
    with patch(SPAM_PATH, return_value=service):
        await view.broadcast_clicked(interaction)
    return interaction


def test_the_key_reaches_the_donate_slider(tmp_path):
    """Safeguard: the name must arrive at mech_donate, not at the fallback."""
    service = SpamProtectionService(config_dir=str(tmp_path))
    assert service.get_button_cooldown("does_not_exist") == 5, "fallback rule changed"
    assert service.get_button_cooldown(EXPECTED_KEY) == 10, (
        f"{EXPECTED_KEY!r} does not reach the operator's donate slider")


@pytest.mark.asyncio
async def test_a_second_press_is_refused(tmp_path):
    """THE FINDING: the button could be pressed as fast as the modal reopens."""
    service = _Recorder(SpamProtectionService(config_dir=str(tmp_path)))
    view = DonationView(donation_manager_available=True)

    first = await _press(view, service)
    second = await _press(view, service)

    assert first.response.send_modal.await_count == 1, "the first press must still work"
    assert second.response.send_modal.await_count == 0, (
        "the second press opened the modal again - anyone in the channel can "
        "write donations into the append-only ledger as fast as they can type")
    assert second.response.send_message.await_count == 1, "the refusal was not sent"


@pytest.mark.asyncio
async def test_the_service_is_asked_and_recorded(tmp_path):
    """And it is asked under the donate slider's name, not a new one."""
    service = _Recorder(SpamProtectionService(config_dir=str(tmp_path)))
    view = DonationView(donation_manager_available=True)

    await _press(view, service)

    assert service.asked == [(USER, EXPECTED_KEY)], service.asked
    assert service.recorded == [(USER, EXPECTED_KEY)], service.recorded


@pytest.mark.asyncio
async def test_with_spam_protection_off_nothing_brakes(tmp_path):
    """Counter-check: the operator's switch still switches it off."""
    service = _Recorder(SpamProtectionService(config_dir=str(tmp_path)))
    view = DonationView(donation_manager_available=True)

    with patch.object(service._real, "is_enabled", return_value=False):
        first = await _press(view, service)
        second = await _press(view, service)

    assert first.response.send_modal.await_count == 1
    assert second.response.send_modal.await_count == 1
    assert service.asked == [], "the service was asked although it is switched off"
