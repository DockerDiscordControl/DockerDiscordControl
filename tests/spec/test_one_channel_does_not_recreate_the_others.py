# -*- coding: utf-8 -*-
"""What one channel decides must not decide it for the channels after it.

THE FINDING (review E23, cogs/docker_control.py): ``_auto_update_ss_messages``
loops over every channel that has an overview message and decides, per
channel, whether to EDIT that message or to delete it and post a new one. The
flag it decides with is ``force_recreate`` - **the function's own parameter**,
reassigned inside the loop at three places (`:3468`, `:3551`, `:3561`).

So the flag is not per channel at all. The first channel whose decision says
"recreate" sets it, and every channel after it in the iteration inherits that
answer without its own decision ever being consulted:

    for channel_id, messages in self.channel_server_message_ids.items():
        ...
        if decision.should_recreate:
            force_recreate = True          # <- the parameter, not a local
        ...
        if force_recreate:
            await message.delete()         # and post a new one
        else:
            await message.edit(...)        # which is what was asked for

``_edit_only_ss_messages`` exists precisely to say "edit, do not recreate" -
it is what runs when somebody expands or collapses a mech panel. Pressing that
button in one channel could delete and repost the overview in a DIFFERENT
channel, which moves that message to the bottom of the channel and gives it a
new id. Which channels it happens to is decided by dictionary order.

The rate limiter three lines below makes the same mistake in the other
direction, and it is the clearer proof that per-channel was the intent:
``should_force_recreate(channel_id)`` takes a channel id, and its answer was
then written to a variable shared by all of them.
"""

import asyncio
from types import SimpleNamespace

import pytest


class _Message:
    def __init__(self, message_id):
        self.id = message_id
        self.deleted = False
        self.edits = 0

    async def delete(self):
        self.deleted = True

    async def edit(self, **_kwargs):
        self.edits += 1


class _Channel:
    def __init__(self, channel_id, message):
        self.id = channel_id
        self.name = f"channel-{channel_id}"
        self._message = message

    async def fetch_message(self, _message_id):
        return self._message


@pytest.fixture
def cog(monkeypatch):
    import cogs.docker_control as docker_control
    from cogs.docker_control import DockerControlCog

    monkeypatch.setattr(docker_control, "load_config", lambda: {"timezone": "UTC"})
    monkeypatch.setattr(docker_control, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: []))
    # The overview update code lives in message_updates.py since the Phase 3 split.
    import cogs.message_updates as message_updates
    monkeypatch.setattr(message_updates, "load_config", lambda: {"timezone": "UTC"})
    monkeypatch.setattr(message_updates, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: []))

    import services.docker_service.server_order as server_order
    monkeypatch.setattr(server_order, "load_server_order", lambda: [])

    # The first channel in order asks to recreate; the second explicitly does not.
    import services.discord.status_overview_service as overview_module

    def decision_for(channel_id, **_kw):
        return SimpleNamespace(should_update=True,
                               should_recreate=(channel_id == 111),
                               reason="test", skip_reason="")

    monkeypatch.setattr(overview_module, "get_status_overview_service",
                        lambda: SimpleNamespace(make_update_decision=decision_for))

    # Mech cache unavailable -> glvl 0, power 0: the override block below is not
    # what this test is about and must not interfere.
    import services.mech.mech_status_cache_service as mech_cache
    monkeypatch.setattr(mech_cache, "get_mech_status_cache_service",
                        lambda: SimpleNamespace(
                            get_cached_status=lambda _r: SimpleNamespace(success=False)))

    messages = {111: _Message(11), 222: _Message(22)}
    channels = {cid: _Channel(cid, msg) for cid, msg in messages.items()}

    instance = DockerControlCog.__new__(DockerControlCog)
    instance.channel_server_message_ids = {111: {"overview": 11}, 222: {"overview": 22}}
    instance.last_message_update_time = {}
    instance.last_channel_activity = {}
    instance.last_glvl_per_channel = {}
    instance.bot = SimpleNamespace(get_channel=lambda cid: channels.get(cid))
    instance.mech_state_manager = SimpleNamespace(
        set_last_glvl=lambda *_a, **_k: None,
        should_force_recreate=lambda *_a, **_k: True,
        mark_force_recreate=lambda *_a, **_k: None)

    locks = {}

    async def _not_interacting(_cid):
        return False

    async def _embed(*_a, **_k):
        return SimpleNamespace(), None

    async def _send(channel, *_a, **_k):
        return SimpleNamespace(id=channel.id * 10)

    instance._create_overview_embed_collapsed = _embed
    instance._send_message_with_files = _send
    instance._persist_tracked_message_ids = lambda: None
    instance._get_channel_lock = lambda cid: locks.setdefault(cid, asyncio.Lock())

    return instance, messages


@pytest.mark.asyncio
async def test_the_second_channel_keeps_its_own_answer(cog, monkeypatch):
    """Channel 111 recreates. Channel 222 said edit, and must be edited."""
    instance, messages = cog

    await instance._auto_update_ss_messages("test", force_recreate=False)

    assert messages[222].deleted is False, (
        "channel 222 decided NOT to recreate and its overview was deleted and "
        "reposted anyway, because channel 111 had set the shared flag first - "
        "the message moves to the bottom of the channel and gets a new id"
    )
    assert messages[222].edits == 1, "channel 222 was not edited either"


@pytest.mark.asyncio
async def test_the_first_channel_still_gets_what_it_asked_for(cog):
    """Counter-check: isolating the flag must not disable the feature."""
    instance, messages = cog

    await instance._auto_update_ss_messages("test", force_recreate=False)

    assert messages[111].deleted is True, (
        "channel 111 asked to recreate and was only edited"
    )
