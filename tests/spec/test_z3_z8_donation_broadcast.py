# -*- coding: utf-8 -*-
# @covers Z3
# @covers Z8
"""Z3/Z8 on the donation broadcast: no guessed success, no silent failure.

Z3 - No success is reported that did not happen.
Z8 - No silent failure on something irreversible.

A thank-you message to a Discord channel is irreversible. It may only go out
once the booking is confirmed - and only to channels that have not
unsubscribed from broadcasts.

Starting point (stage 0): there were **zero** tests on this entire path. Two
paths send the same message, and only one of them is careful:

* ``check_donation_notifications`` (docker_control.py:5165-5180) reads
  ``donation_broadcasts`` and sends only to channels that allow it.
* ``DonationBroadcastModal.callback`` (:4919-4946) walks the same
  ``channel_permissions`` list and **never** reads the flag.

Two paths lead here to a thank-you message without a booking:

1. If ``process_discord_donation`` raises, :4885-4887 catches the exception, sets
   ``evolution_occurred = False`` - and execution falls into the broadcast
   block at :4889. (A reported ``success=False``, by contrast, correctly leads
   to an early ``return`` at :4831-4837.)
2. If ``donation_manager_available`` is false, nothing is booked at :4789 in
   the first place - the broadcast runs anyway.

On robustness, honestly: this runs against imitated Discord objects.
It proves which calls the code triggers, not that Discord executes them that
way. Real proof would only come from the running bot.

The modal is deliberately not built via ``__init__``: the constructor pulls in
py-cord machinery and calls the real progress service via
``_get_dynamic_amount_placeholder()``. What is to be checked is ``callback``,
not the scaffolding.

COUNTER-CHECK (carried out 2026-09-16) - the way there is part of it:

*Two false starts, both my fault.* The first two runs were red with
``TypeError: 'MagicMock' object can't be awaited`` at :4964 - the stub did
not stub ``edit_original_response``. Red for the wrong reason proves
nothing; the stub was corrected, not the code. The list of ``await`` calls
to stub has since come from a complete search over :4731-4990 instead of
from repeated trial and error.

*Then justified red*, all three on their own assertion:

* ``...booking_raises``             -> ``assert {100: 1, 200: 1} == {100: 0, 200: 0}``
* ``...without_booking_service``    -> the same form
* ``...unsubscribed_channels``      -> ``assert 1 == 0``

*The first fix was incomplete, and the test showed it:* afterwards the result
was ``{100: 1, 200: 0}`` - the opt-out took effect, the booking block did not.
It depended on ``donation_amount_euros``, which is only assigned INSIDE the
skipped booking block (:4807) and therefore stayed ``None``. Switched to
``amount`` (the validated user input, set at :4753-4773). After that 14 green.

The permitted side of the block - without a stated amount the
"X supports DDC" message should still go out - is covered by
``test_without_amount_the_support_message_goes_out``. Without this case
one could tighten the block to "always block" and everything would stay
green.

This test also ran into a bug of its own and uncovered it:
``new_power = new_state.Power`` ran unconditionally, also in the ``else``
branch, in which ``new_state`` is never assigned. The line was also redundant -
both branches already set ``new_power``. The resulting ``UnboundLocalError``
(not NameError, as it first said here) fell through both ``except`` blocks,
the final response was never sent, and the user saw "Processing..."
permanently. Two more unconditional accesses to ``new_state.level`` stood
next to it; all three were switched to ``new_evolution_level``, which is set
in both branches.

Counter-check for that: before,
``UnboundLocalError: cannot access local variable 'new_state'`` (1 red, 14
green), afterwards 15 green. The complete list of ``new_state`` accesses
was compiled before the fix, not discovered through repeated runs.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.docker_control import DonationBroadcastModal


def _interaction():
    """Imitated interaction - shaped as in tests/unit/cogs/test_enhanced_info_modal.py:42.

    Every stub covers a concrete ``await`` in the callback; the list comes
    from a complete search over :4731-4990, not from repeated trial and
    error:

    * ``response.send_message``      -> :4738
    * ``followup.send``              -> :4776, :4814, :4836
    * ``edit_original_response``     -> :4964, :4984
    * ``<followup result>.delete``   -> :4969, :4979

    The last item would be dispensable, because :4970 is a bare ``except: pass`` -
    exactly the kind of swallowing that Z8 forbids. Relying on it in the test
    would mean using a bug as a support.
    """
    inter = MagicMock()
    inter.response.send_message = AsyncMock()

    processing_message = MagicMock()
    processing_message.delete = AsyncMock()
    inter.followup.send = AsyncMock(return_value=processing_message)

    inter.edit_original_response = AsyncMock()
    inter.user.name = "Donor"
    inter.user.id = 4711
    inter.guild.id = 1
    inter.channel.id = 2
    inter.id = 999
    return inter


def _modal(*, manager_available: bool = True, amount: str = "5.00", share: str = "X"):
    """Modal without the py-cord constructor, with the three fields callback reads."""
    m = DonationBroadcastModal.__new__(DonationBroadcastModal)
    m.donation_manager_available = manager_available
    m.bot = MagicMock()
    m.name_input = SimpleNamespace(value="Donor")
    m.amount_input = SimpleNamespace(value=amount)
    m.share_input = SimpleNamespace(value=share)
    return m


def _channels(*channel_configs):
    """(config dict, {id: channel}) for the given channels."""
    config = {"channel_permissions": {}}
    channels = {}
    for channel_id, broadcasts in channel_configs:
        config["channel_permissions"][str(channel_id)] = {"donation_broadcasts": broadcasts}
        channel_mock = MagicMock()
        channel_mock.send = AsyncMock()
        channels[channel_id] = channel_mock
    return config, channels


def _mech_service_stub():
    """Supplies states so that the callback gets as far as the broadcast."""
    state = SimpleNamespace(success=True, level=1, power=10.0)
    service = MagicMock()
    service.get_mech_state_service = MagicMock(return_value=state)
    return service


@pytest.fixture
def env():
    """Patches exactly the dependencies that callback fetches from outside."""
    config, channels = _channels((100, True), (200, False))
    with patch("cogs.donation_ui.load_config", return_value=config), \
         patch("services.mech.mech_service.get_mech_service",
               return_value=_mech_service_stub()):
        yield channels


def _sent(channels):
    return {kid: k.send.await_count for kid, k in channels.items()}


async def test_no_thank_you_message_if_the_booking_raises(env):
    """If the booking service raises, nothing may go out."""
    inter = _interaction()
    inter.client.get_channel = lambda kid: env.get(int(kid))

    with patch("services.donation.unified_donation_service.process_discord_donation",
               AsyncMock(side_effect=RuntimeError("donation ledger not writable"))):
        await _modal().callback(inter)

    assert _sent(env) == {100: 0, 200: 0}, (
        "The booking failed, but a thank-you message went out - "
        "the channel reports money that never landed in the ledger"
    )


async def test_no_thank_you_message_without_booking_service(env):
    """If the booking service is unavailable, nothing is booked - and nothing is sent."""
    inter = _interaction()
    inter.client.get_channel = lambda kid: env.get(int(kid))

    await _modal(manager_available=False).callback(inter)

    assert _sent(env) == {100: 0, 200: 0}, (
        "Without a booking service nothing was booked, yet thanks were given anyway"
    )


async def test_broadcast_respects_unsubscribed_channels(env):
    """A channel with donation_broadcasts=False gets nothing.

    The parallel path in check_donation_notifications (:5168) has long honoured
    the flag; this path must follow the same rule, otherwise it is the same
    rule in two places with two results.
    """
    inter = _interaction()
    inter.client.get_channel = lambda kid: env.get(int(kid))

    success_result = SimpleNamespace(
        success=True,
        new_state=SimpleNamespace(level=1, Power=15.0),
        error_message=None,
    )
    with patch("services.donation.unified_donation_service.process_discord_donation",
               AsyncMock(return_value=success_result)):
        await _modal().callback(inter)

    sent = _sent(env)
    assert sent[200] == 0, (
        "Channel 200 unsubscribed from donation broadcasts, but still got a "
        "message"
    )
    assert sent[100] == 1, (
        "Channel 100 allows broadcasts and should have received the message"
    )


async def test_without_amount_the_support_message_goes_out(env):
    """Without a stated amount there is nothing to book - the message may still go out.

    This is the PERMITTED side of the block from the tests above. Without this
    case one could tighten the block to "always block" and everything would
    stay green - an intended behaviour would have silently disappeared.

    Also covers :4870: without an amount the code runs into the ``else`` branch
    at :4844, in which ``new_state`` is never assigned, and still accesses it
    at :4870. The ``NameError`` falls through both ``except`` blocks;
    the user would be stuck on "Processing...", because :4964 is never reached.
    """
    inter = _interaction()
    inter.client.get_channel = lambda kid: env.get(int(kid))

    await _modal(amount="").callback(inter)

    sent = _sent(env)
    assert sent[100] == 1, (
        "The support message without an amount did not go out - the block "
        "took an intended case along with it"
    )
    assert sent[200] == 0, "Unsubscribed channel still got a message"
    assert inter.edit_original_response.await_count == 1, (
        "The user got no final response and would keep seeing 'Processing...'"
    )
