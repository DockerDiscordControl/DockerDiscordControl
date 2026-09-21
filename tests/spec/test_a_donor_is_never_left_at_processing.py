# -*- coding: utf-8 -*-
"""A donor who pressed Submit must be told what happened. Always.

THE FINDING (review E19, cogs/docker_control.py): ``DonationBroadcastModal.callback``
opens by answering the interaction with ``⏳ Processing...``, so the modal closes
and Discord is satisfied. Every path after that owes the donor a replacement for
that message. Two of them do not give one:

1. ``if not old_state_result.success: logger.error(...); return`` and the same
   three lines later for ``new_state_result`` - a bare ``return``, no followup,
   no edit. Between those two sits the failure path for the booking itself,
   which does it properly: it deletes the public processing message and sends
   "❌ Donation processing failed: ...". Three failure paths in one function,
   one of them answering and two of them silent.

2. The handler around the whole callback lists
   ``(discord.errors.DiscordException, RuntimeError, ValueError)``. The mech
   service raises ``MechStateError -> MechServiceError -> DDCBaseException``,
   which is in none of them, so it left the callback entirely - past the cleanup
   that deletes the public "Processing a $X donation" message, and past the
   ``edit_original_response`` that would have said something.

The visible result is the same in both cases and it is the worst one this
feature has: the donor filled in their name and their amount, pressed Submit,
and watched "⏳ Processing..." forever. Somebody who has just given money and is
told nothing assumes it did not work, and gives again.

Nothing is lost from the ledger in case 1 - the return happens before the
booking. That is not the point. The point is that the donor cannot know it.
"""

import pytest

import discord

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


def _modal(amount="10.00"):
    from cogs.docker_control import DonationBroadcastModal

    modal = DonationBroadcastModal.__new__(DonationBroadcastModal)
    modal.donation_manager_available = True
    modal.bot = None
    modal.name_input = _Input("Donor")
    modal.amount_input = _Input(amount)
    modal.share_input = _Input("")          # keep it private: no channel work
    return modal


def _answers(interaction):
    """Everything the donor could actually have seen after 'Processing...'."""
    return [text for text in interaction.followups + interaction.edits if text]


@pytest.mark.asyncio
async def test_an_unreadable_mech_state_still_answers_the_donor(monkeypatch):
    """The 'Failed to get old mech state' path used to just return."""
    import services.mech.mech_service as mech_service

    class _Result:
        success = False
        level = None
        power = None

    class _Service:
        def get_mech_state_service(self, _request):
            return _Result()

    monkeypatch.setattr(mech_service, "get_mech_service", lambda: _Service())

    interaction = _Interaction()
    await _modal().callback(interaction)

    assert _answers(interaction), (
        "the donor pressed Submit and was left looking at '⏳ Processing...' "
        "with no word about what happened"
    )


@pytest.mark.asyncio
async def test_a_raising_mech_service_still_answers_the_donor(monkeypatch):
    """A DDC exception is in none of the handler's three types."""
    import services.mech.mech_service as mech_service

    class _Service:
        def get_mech_state_service(self, _request):
            raise MechStateError("the snapshot lags behind the event log")

    monkeypatch.setattr(mech_service, "get_mech_service", lambda: _Service())

    interaction = _Interaction()
    await _modal().callback(interaction)

    assert _answers(interaction), (
        "a mech exception left the callback entirely; the donor saw "
        "'⏳ Processing...' and nothing else, for ever"
    )


@pytest.mark.asyncio
async def test_the_donor_is_not_thanked_for_a_donation_that_failed(monkeypatch):
    """Counter-check: answering must not become answering WRONGLY (SPEC Z3)."""
    import services.mech.mech_service as mech_service

    class _Service:
        def get_mech_state_service(self, _request):
            raise MechStateError("the snapshot lags behind the event log")

    monkeypatch.setattr(mech_service, "get_mech_service", lambda: _Service())

    interaction = _Interaction()
    await _modal().callback(interaction)

    joined = " ".join(_answers(interaction))
    assert "Thank you" not in joined, (
        f"the donor was thanked for money the ledger never saw: {joined!r}"
    )
