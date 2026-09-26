# -*- coding: utf-8 -*-
"""/donate is a thank-you, not a megaphone into every DDC channel.

THE FINDING (spam and Discord-input audits, 2026-09-26): anybody could run
/donate in any channel of the guild, press Broadcast, leave the amount empty
and type "[Claim your reward](https://evil.example)" as the name. The bot then
posted "**<that link>** supports DDC" into EVERY DDC channel, the control
channels included - with its own voice, as often as the ten-second spam
cooldown allowed, and not at all braked when spam protection was off.

THE OPERATOR'S DECISION (2026-09-26: contain it, five minutes per person):

1. /donate works only in DDC's own channels (those in channel_permissions);
2. a broadcast needs an amount, and so a booking;
3. one person broadcasts at most once per five minutes - another person is
   not held back by it;
4. the donor name is text, never markdown.

HOW THIS TEST CAN FAIL: it runs the command and the Broadcast modal against
imitated Discord objects and counts what reaches the channels. Each rule has
its own case, and the last cases keep the everyday path open - a second person
right after the first, and a booked donation in a DDC channel.

COUNTER-CHECK (2026-09-26): red before on all four rules - the panel came up
in a foreign channel, the amountless message went out, the second broadcast
of one person went out, the name kept its brackets. Sabotage afterwards:
BROADCAST_EVERY_SECONDS = 0 turns the per-person case red and leaves the
second-person case green; dropping escape_markdown turns only the name case red.
"""

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cogs.donation_ui as donation_ui
from cogs.donation_ui import DonationBroadcastModal


# ---- the command ---------------------------------------------------------

class _Ctx:
    def __init__(self, channel_id):
        self.sent = []
        self.channel_id = channel_id
        self.author = MagicMock()
        self.channel = MagicMock()
        self.guild = MagicMock()
        self.followup = MagicMock()

        async def defer(**kwargs):
            return None

        async def send(*args, **kwargs):
            self.sent.append({"content": args[0] if args else kwargs.get("content"),
                              "embed": kwargs.get("embed"),
                              "ephemeral": kwargs.get("ephemeral", False)})
            return MagicMock()

        self.defer = defer
        self.followup.send = send


def _run_donate(ctx, monkeypatch):
    from cogs.slash_commands import SlashCommandsMixin

    monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled",
                        lambda: False)
    monkeypatch.setattr("cogs.slash_commands.load_config",
                        lambda: {"channel_permissions": {"55": {}}})
    cog = MagicMock()
    cog._check_spam_protection = AsyncMock(return_value=True)
    cog.bot = MagicMock()
    asyncio.run(SlashCommandsMixin.donate_command.callback(cog, ctx))


def test_a_foreign_channel_gets_no_donation_panel(monkeypatch):
    ctx = _Ctx(channel_id=77)

    _run_donate(ctx, monkeypatch)

    assert not any(m["embed"] is not None for m in ctx.sent), (
        "/donate built its panel in a channel DDC does not own")
    assert ctx.sent and all(m["ephemeral"] for m in ctx.sent), (
        "the caller was not told, privately, why nothing came")


def test_a_ddc_channel_still_gets_the_panel(monkeypatch):
    ctx = _Ctx(channel_id=55)

    _run_donate(ctx, monkeypatch)

    assert any(m["embed"] is not None for m in ctx.sent), (
        "the everyday case: /donate in a DDC channel must still work")


# ---- the Broadcast modal -------------------------------------------------

def _interaction(user_id):
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    processing = MagicMock()
    processing.delete = AsyncMock()
    inter.followup.send = AsyncMock(return_value=processing)
    inter.edit_original_response = AsyncMock()
    inter.user.name = f"user{user_id}"
    inter.user.id = user_id
    inter.guild.id = 1
    inter.channel.id = 2
    inter.id = 999
    return inter


def _modal(*, amount="5.00", name="Donor"):
    m = DonationBroadcastModal.__new__(DonationBroadcastModal)
    m.donation_manager_available = True
    m.bot = MagicMock()
    m.name_input = SimpleNamespace(value=name)
    m.amount_input = SimpleNamespace(value=amount)
    m.share_input = SimpleNamespace(value="X")
    return m


@pytest.fixture
def channel():
    getattr(donation_ui, "_last_broadcast", {}).clear()
    target = MagicMock()
    target.send = AsyncMock()
    booked = SimpleNamespace(success=True, new_state=SimpleNamespace(level=1, Power=15.0),
                             error_message=None)
    state = SimpleNamespace(success=True, level=1, power=10.0)
    mech = MagicMock()
    mech.get_mech_state_service = MagicMock(return_value=state)
    with patch("cogs.donation_ui.load_config",
               return_value={"channel_permissions": {"100": {"donation_broadcasts": True}}}), \
         patch("services.mech.mech_service.get_mech_service", return_value=mech), \
         patch("services.donation.unified_donation_service.process_discord_donation",
               AsyncMock(return_value=booked)):
        yield target
    getattr(donation_ui, "_last_broadcast", {}).clear()


def _send(modal, user_id, target):
    inter = _interaction(user_id)
    inter.client.get_channel = lambda _cid: target
    asyncio.run(modal.callback(inter))
    return inter


def _final_text(inter):
    return str(inter.edit_original_response.await_args)


def test_no_amount_no_broadcast(channel):
    inter = _send(_modal(amount=""), 1, channel)

    assert channel.send.await_count == 0, (
        "an amountless 'X supports DDC' still went into the DDC channels")
    assert "amount" in _final_text(inter), "the user was not told why nothing went out"


def test_one_person_broadcasts_once_per_five_minutes(channel):
    _send(_modal(), 1, channel)
    inter = _send(_modal(), 1, channel)

    assert channel.send.await_count == 1, (
        "the same person broadcast twice within five minutes")
    assert "five minutes" in _final_text(inter), "the user was not told about the brake"


def test_another_person_is_not_held_back(channel):
    _send(_modal(), 1, channel)
    _send(_modal(), 2, channel)

    assert channel.send.await_count == 2, (
        "the brake is PER PERSON - a second donor must still be thanked")


def test_the_slot_opens_again_after_five_minutes():
    getattr(donation_ui, "_last_broadcast", {}).clear()
    assert donation_ui._broadcast_slot(1, now=1000.0)
    assert not donation_ui._broadcast_slot(1, now=1000.0 + 299)
    assert donation_ui._broadcast_slot(1, now=1000.0 + 300)
    getattr(donation_ui, "_last_broadcast", {}).clear()


def test_the_donor_name_is_text_not_markdown(channel):
    _send(_modal(name="[Claim](https://evil.example)"), 1, channel)

    # escape_markdown turns "[" into "\\[", which Discord shows as a bracket
    # and never as a link; an UNESCAPED "[" is what renders.
    embed = channel.send.await_args.kwargs["embed"]
    assert not re.search(r"(?<!\\)\[Claim\]\(", embed.description), (
        f"the name rendered as a masked link: {embed.description!r}")
