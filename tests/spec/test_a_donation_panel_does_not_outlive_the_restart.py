# -*- coding: utf-8 -*-
"""A donation panel left behind by a restart is cleared away, not left dead.

THE FINDING (independent review of the cog modules, 2026-09-23; measured here):
/donate posts its panel NON-ephemerally and gives it a life of about fifteen
minutes - DonationView has timeout=890 and an auto-delete timer at 885 s, and
on timeout the view deletes its own message. So under normal operation there
is no dead button; the design is that the panel is temporary.

The view and its timer live in memory. The message does not. A restart inside
that fifteen-minute window - and a rebuild takes the bot offline for 60-90
seconds, so it is not a theoretical window - leaves the message in the channel
with a "Broadcast Donation" button that looks live and does nothing. Pressing
it gets Discord's "This interaction failed" and writes nothing to the log,
because from the bot's side nothing happened at all. The message never goes
away by itself: the only thing that would have deleted it died with the view.

OPERATOR DECISION (2026-09-23): clear it away at startup, rather than making
the panel persistent. That keeps what the panel already is - something that
appears, is used and disappears - instead of leaving a donation panel standing
in the channel until somebody removes it by hand.

It uses the machinery that is already there for the overviews: the message id
goes into mech_state.json under the channel, and the bot deletes it by id when
it comes back. Measured before building: that map already survives restarts
and already holds 'overview' and 'admin_overview' for the two live channels.

HOW THIS TEST CAN FAIL: it posts a panel, restarts around it and asks whether
the message is gone and the id forgotten. A panel that survives is red, and so
is an id that stays in the map after the message was deleted - the next
startup would chase a message that is not there.

COUNTER-CHECK (2026-09-23): red before - /donate recorded nothing, the persist
filter dropped anything that was not an overview, and no startup step looked
for a donation panel.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


class _Channel:
    """A channel that hands out partial messages and remembers the deletes."""

    def __init__(self, channel_id, fails_with=None):
        self.id = channel_id
        self.deleted = []
        self._fails_with = fails_with

    def get_partial_message(self, message_id):
        partial = MagicMock()

        async def delete():
            if self._fails_with:
                raise self._fails_with
            self.deleted.append(message_id)

        partial.delete = delete
        return partial


def _cog_with(tracked):
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.channel_server_message_ids = tracked
    cog.mech_state_manager = MagicMock()
    return cog


def test_the_panel_id_is_kept_across_a_restart():
    """THE FINDING, first half: nothing remembered the message at all.

    The filter is what drops it - it kept only the two overview kinds, so a
    donation id written into the map never reached mech_state.json.
    """
    cog = _cog_with({4242: {"donation": 99, "overview": 7}})

    cog._persist_tracked_message_ids()

    key, snapshot = cog.mech_state_manager.set_state.call_args.args
    assert key == "channel_overview_message_ids"
    assert snapshot["4242"] == {"donation": 99, "overview": 7}


def test_a_restored_panel_id_is_read_back(tmp_path, monkeypatch):
    """Counter-check: writing it is worth nothing if the restore drops it."""
    import cogs.docker_control as module

    restored = module._restored_tracked_message_ids(
        {"channel_overview_message_ids": {"55": {"donation": 12, "overview": 13}}})

    assert restored == {55: {"donation": 12, "overview": 13}}


def test_a_key_nobody_knows_is_not_restored():
    """Counter-check: the map is a fixed set of roles, not a junk drawer."""
    import cogs.docker_control as module

    restored = module._restored_tracked_message_ids(
        {"channel_overview_message_ids": {"55": {"something_else": 12}}})

    assert restored == {}


@pytest.mark.asyncio
async def test_the_startup_step_removes_the_panel_and_forgets_it():
    """THE POINT: the message left behind by the restart is gone afterwards."""
    from app.bot.startup_steps.donation_panels import remove_stale_donation_panels_step

    channel = _Channel(4242)
    cog = _cog_with({4242: {"donation": 99, "overview": 7}})
    context = MagicMock()
    context.bot.get_cog.return_value = cog
    context.bot.get_channel.return_value = channel

    await remove_stale_donation_panels_step(context)

    assert channel.deleted == [99], "the stale donation panel is still there"
    assert cog.channel_server_message_ids[4242] == {"overview": 7}, "the id was not forgotten"
    cog.mech_state_manager.set_state.assert_called()


@pytest.mark.asyncio
async def test_an_overview_is_not_touched():
    """Counter-check: the overviews have their own lifecycle and must survive.

    Deleting them here would remove the message the channel is FOR on every
    single restart.
    """
    from app.bot.startup_steps.donation_panels import remove_stale_donation_panels_step

    channel = _Channel(4242)
    cog = _cog_with({4242: {"overview": 7, "admin_overview": 8}})
    context = MagicMock()
    context.bot.get_cog.return_value = cog
    context.bot.get_channel.return_value = channel

    await remove_stale_donation_panels_step(context)

    assert channel.deleted == []
    assert cog.channel_server_message_ids[4242] == {"overview": 7, "admin_overview": 8}


@pytest.mark.asyncio
async def test_a_panel_that_is_already_gone_is_simply_forgotten():
    """Counter-check: the everyday case. The view usually deleted it itself."""
    from app.bot.startup_steps.donation_panels import remove_stale_donation_panels_step

    channel = _Channel(4242, fails_with=discord.NotFound(MagicMock(status=404), "gone"))
    cog = _cog_with({4242: {"donation": 99}})
    context = MagicMock()
    context.bot.get_cog.return_value = cog
    context.bot.get_channel.return_value = channel

    await remove_stale_donation_panels_step(context)

    assert cog.channel_server_message_ids[4242] == {}


@pytest.mark.asyncio
async def test_a_panel_that_could_not_be_deleted_keeps_its_id():
    """Counter-check: a refusal is not a delete.

    Forgetting the id after a 403 would strand the panel for good - the next
    startup would not know about it any more, and nothing else ever will.
    """
    from app.bot.startup_steps.donation_panels import remove_stale_donation_panels_step

    channel = _Channel(4242, fails_with=discord.Forbidden(MagicMock(status=403), "no"))
    cog = _cog_with({4242: {"donation": 99}})
    context = MagicMock()
    context.bot.get_cog.return_value = cog
    context.bot.get_channel.return_value = channel

    await remove_stale_donation_panels_step(context)

    assert cog.channel_server_message_ids[4242] == {"donation": 99}


@pytest.mark.asyncio
async def test_a_channel_the_bot_cannot_see_does_not_stop_the_startup():
    """Counter-check: a step that raises takes the rest of the startup with it."""
    from app.bot.startup_steps.donation_panels import remove_stale_donation_panels_step

    cog = _cog_with({4242: {"donation": 99}})
    context = MagicMock()
    context.bot.get_cog.return_value = cog
    context.bot.get_channel.return_value = None

    await remove_stale_donation_panels_step(context)  # must not raise

    assert cog.channel_server_message_ids[4242] == {"donation": 99}


@pytest.mark.asyncio
async def test_no_cog_is_not_a_crash():
    """Counter-check: the extensions step runs before this one, but a failed
    load must not turn into a second failure here."""
    from app.bot.startup_steps.donation_panels import remove_stale_donation_panels_step

    context = MagicMock()
    context.bot.get_cog.return_value = None

    await remove_stale_donation_panels_step(context)  # must not raise


def test_the_step_is_in_the_startup_sequence():
    """A step nobody runs is a file."""
    from app.bot.startup_steps import STARTUP_STEPS
    from app.bot.startup_steps.commands import load_extensions_step
    from app.bot.startup_steps.donation_panels import remove_stale_donation_panels_step

    names = [getattr(step, "step_name", "") for step in STARTUP_STEPS]

    assert "remove_stale_donation_panels_step" in names
    # After the extensions: the cog it asks for does not exist before them.
    assert names.index("remove_stale_donation_panels_step") > names.index(
        getattr(load_extensions_step, "step_name"))


def test_donate_records_the_panel_it_posted():
    """Counter-check on the other end: a startup step that cleans up something
    nobody recorded cleans up nothing."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "cogs"
              / "slash_commands.py").read_text(encoding="utf-8")

    assert '"donation"] = message.id' in source or "'donation'] = message.id" in source, \
        "/donate does not record the panel it posted"
