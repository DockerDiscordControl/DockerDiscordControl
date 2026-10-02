# -*- coding: utf-8 -*-
"""The overview moves to the bottom when someone else wrote under it - not for DDC's own passing notices.

THE OPERATOR (2026-10-02): the point is that nobody has to scroll to reach
the overview. DDC's own notices that expire by themselves are ignored; when
a person or anything that is not this DDC posts, the channel's inactivity
timer runs (10 minutes on their host) and the overview is posted anew at the
bottom.

THE FINDINGS, both seen while answering that:
- the check looked at the LAST message only. A person writing and a join
  notice right after it kept the overview up there until the notice expired
  (30 minutes; an hour for an auto-action notice);
- on_message ignored every bot, so another bot or a webhook posting under the
  overview never started the timer.

THE CONTRACT: every message under the overview counts. One that is not this
DDC's moves the overview after the timer; one of DDC's own moves it unless
it is a managed overview or its lifetime still runs. A message from anyone
but this DDC starts the timer.

HOW THIS TEST CAN FAIL: a person's message hidden behind a notice is
ignored again, another bot's post does not start the timer, or a passing
notice moves the overview.

COUNTER-CHECK (2026-10-02): red before the change (no decision function;
the other bot's post left the timer alone).
"""

from types import SimpleNamespace

import pytest

from tests.spec.test_every_public_message_has_its_lifetime import _Channel, lifetimes  # noqa: F401

DDC = 7000


def _message(message_id, author_id, application_id=None):
    return SimpleNamespace(id=message_id, author=SimpleNamespace(id=author_id, name=f"u{author_id}"),
                           application_id=application_id)


def _decide(below, alive=frozenset()):
    from cogs.channel_lifecycle import why_the_overview_must_move
    return why_the_overview_must_move(below, own_ids={DDC}, managed_ids={9001, 9002}, alive_ids=set(alive))


def test_a_person_behind_a_passing_notice_still_moves_it():
    below = [_message(10, 555), _message(11, DDC)]          # a person, then a join notice
    assert _decide(below, alive={11}) is not None


def test_another_bot_moves_it():
    assert _decide([_message(10, 8888)]) is not None


def test_passing_notices_and_the_other_overview_do_not():
    below = [_message(9002, DDC), _message(11, DDC), _message(12, DDC)]
    assert _decide(below, alive={11, 12}) is None


def test_a_ddc_message_without_a_running_lifetime_does():
    assert _decide([_message(13, DDC)], alive=set()) is not None


def test_ddc_recognised_by_its_application_id():
    message = _message(14, 1, application_id=DDC)
    from cogs.channel_lifecycle import why_the_overview_must_move
    assert why_the_overview_must_move([message], own_ids={DDC}, managed_ids={9001},
                                      alive_ids={14}) is None


@pytest.mark.asyncio
async def test_another_bot_starts_the_timer():
    from cogs.docker_control import DockerControlCog
    cog = DockerControlCog.__new__(DockerControlCog)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=DDC), application_id=DDC)
    cog.last_channel_activity = {}
    cog._config_service = SimpleNamespace(get_config=lambda: {"channel_permissions": {
        "111": {"recreate_messages_on_inactivity": True, "inactivity_timeout_minutes": 10}}})

    def message(author_id, bot):
        return SimpleNamespace(author=SimpleNamespace(id=author_id, bot=bot), guild=object(),
                               channel=SimpleNamespace(id=111), application_id=None)
    await cog.on_message(message(DDC, True))
    assert cog.last_channel_activity == {}, "DDC's own post started the timer"
    await cog.on_message(message(8888, True))
    assert 111 in cog.last_channel_activity, "another bot's post did not start the timer"


# --- the inactivity loop itself ---------------------------------------------------------

@pytest.fixture
def channel_below(monkeypatch):
    """A cog whose status channel 111 holds the overview 9001 and ``below`` under it."""
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock

    import discord

    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    config = {"channel_permissions": {"111": {"recreate_messages_on_inactivity": True,
                                              "inactivity_timeout_minutes": 10}}}
    monkeypatch.setattr(loops, "load_config", lambda: config)
    monkeypatch.setattr(loops, "_channel_has_permission", lambda cid, perm, cfg: perm == "serverstatus")

    def build(below):
        cog = DockerControlCog.__new__(DockerControlCog)
        cog.initial_messages_sent = True
        cog.channel_server_message_ids = {111: {"overview": 9001}}
        cog.last_channel_activity = {111: datetime.now(timezone.utc) - timedelta(minutes=11)}
        channel = MagicMock(spec=discord.TextChannel)
        channel.name, channel.id = "tech", 111

        def history(limit=None, after=None):
            messages = below if after is not None else list(reversed(below))[:limit]
            return SimpleNamespace(flatten=lambda: _ready(messages))
        channel.history = history

        async def fetch_channel(channel_id):
            return channel
        cog.bot = SimpleNamespace(user=SimpleNamespace(id=DDC), application_id=DDC, fetch_channel=fetch_channel,
                                  get_channel=lambda cid: SimpleNamespace(last_message_id=below[-1].id))
        regenerated = []

        async def regenerate(channel, mode, cfg):
            regenerated.append(mode)
        cog._regenerate_channel = regenerate
        return cog, regenerated
    return build


async def _ready(value):
    return value


@pytest.mark.asyncio
async def test_the_loop_moves_it_for_a_person_behind_a_notice(lifetimes, channel_below):  # noqa: F811
    module, clock = lifetimes
    notice = await module.post(_Channel(111), "player_join", "👋 Anna joined")
    cog, regenerated = channel_below([_message(10, 555), _message(notice.id, DDC)])
    await cog.inactivity_check_loop.coro(cog)
    assert regenerated == ["status"]


@pytest.mark.asyncio
async def test_the_loop_leaves_it_for_passing_notices(lifetimes, channel_below):  # noqa: F811
    module, clock = lifetimes
    notice = await module.post(_Channel(111), "player_join", "👋 Anna joined")
    cog, regenerated = channel_below([_message(notice.id, DDC)])
    await cog.inactivity_check_loop.coro(cog)
    assert regenerated == []
