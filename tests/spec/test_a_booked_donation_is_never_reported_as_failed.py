# -*- coding: utf-8 -*-
"""A donation the ledger already took is never reported to the donor as failed.

THE FINDING (independent review of the donation path, 2026-09-23): everything
after the confirmed booking in DonationBroadcastModal - reading the config,
walking the channels, building the embed, writing the answer - sits inside one
broad `except Exception`, and that handler says:

    ❌ Error sending donation broadcast. Please try again later.

for money that is already in the ledger. "Please try again later" is the worst
possible sentence there, because the Discord path is NOT protected against a
retry: the idempotency key is `interaction.id`, and resubmitting the modal is a
new interaction with a new id. The second attempt books a second DonationAdded.

What that costs: two donations of $50 in the history for one payment, a mech
two levels further along than it earned, and an append-only log that can only
be corrected one seq at a time in the panel.

The donor must be told the truth: the donation IS recorded, only the
announcement failed, and they must NOT submit again.

HOW THIS TEST CAN FAIL: it books a donation, then makes the step right after
it raise, and reads what the donor is told. If the answer invites another
attempt, the test is red.

COUNTER-CHECK (2026-09-23): red before - "Please try again later" for a booked
donation. The last test keeps the other side: when nothing was booked, the
donor is still asked to try again, because then there is nothing to lose.
"""

import pytest

from services.exceptions import MechStateError


class _Response:
    def __init__(self):
        self.sent = []

    async def send_message(self, content, **kwargs):
        self.sent.append(content)


class _Interaction:
    def __init__(self):
        self.response = _Response()
        self.followups = []
        self.edits = []
        self.user = type("U", (), {"name": "donor", "id": 4242})()
        self.guild = None
        self.channel = None
        self.id = 777
        self.client = None

    @property
    def followup(self):
        interaction = self

        class _Followup:
            async def send(self, content, **kwargs):
                interaction.followups.append(content)
                return None

        return _Followup()

    async def edit_original_response(self, content=None, **kwargs):
        self.edits.append(content)


class _Input:
    def __init__(self, value):
        self.value = value


def _modal(share="yes"):
    from cogs.donation_ui import DonationBroadcastModal

    modal = DonationBroadcastModal.__new__(DonationBroadcastModal)
    modal.donation_manager_available = True
    modal.bot = None
    modal.name_input = _Input("Donor")
    modal.amount_input = _Input("50.00")
    modal.share_input = _Input(share)
    return modal


def _answers(interaction):
    return [text for text in interaction.followups + interaction.edits if text]


class _State:
    success = True
    level = 3
    power = 100
    power_max = 1000
    total_donated = 50.0


class _MechService:
    def get_mech_state_service(self, _request):
        return _State()


@pytest.fixture
def booked(monkeypatch):
    """A ledger that confirms the booking, and a config read that then fails."""
    import services.mech.mech_service as mech_service
    import services.donation.unified_donation_service as unified

    monkeypatch.setattr(mech_service, "get_mech_service", lambda: _MechService())

    async def process(**kwargs):
        return type("R", (), {"success": True, "new_state": _State(),
                              "error_message": None})()

    monkeypatch.setattr(unified, "process_discord_donation", process)
    # The first thing after the booking that reaches outside the function.
    import cogs.donation_ui as donation_ui

    def explode():
        raise MechStateError("the configuration could not be read")

    monkeypatch.setattr(donation_ui, "load_config", explode)


@pytest.mark.asyncio
async def test_the_donor_is_not_asked_to_try_again(booked):
    """THE FINDING: the retry books the same money a second time."""
    interaction = _Interaction()
    await _modal().callback(interaction)

    joined = " ".join(_answers(interaction))
    assert joined, "the donor was told nothing at all"
    assert "try again" not in joined.lower(), (
        f"the donor was asked to resubmit a donation the ledger already took: {joined!r}")


@pytest.mark.asyncio
async def test_the_donor_is_told_the_donation_was_recorded(booked):
    """Because it was - only the announcement failed."""
    interaction = _Interaction()
    await _modal().callback(interaction)

    joined = " ".join(_answers(interaction)).lower()
    assert "recorded" in joined or "saved" in joined, (
        f"nothing told the donor their money is in the ledger: {joined!r}")


@pytest.mark.asyncio
async def test_a_donation_that_was_never_booked_may_still_be_retried(monkeypatch):
    """Counter-check: with nothing in the ledger, trying again is right."""
    import services.mech.mech_service as mech_service

    class _Raises:
        def get_mech_state_service(self, _request):
            raise MechStateError("the snapshot lags behind the event log")

    monkeypatch.setattr(mech_service, "get_mech_service", lambda: _Raises())

    interaction = _Interaction()
    await _modal().callback(interaction)

    joined = " ".join(_answers(interaction))
    assert joined, "the donor was told nothing at all"
    assert "Thank you" not in joined, "thanked for money the ledger never saw"
