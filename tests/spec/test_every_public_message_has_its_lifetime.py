# -*- coding: utf-8 -*-
"""Every public message DDC posts has its lifetime - and keeps it over a restart.

THE OPERATOR (2026-09-30): every message but the status and control
overviews should have a lifetime. The lifetimes they chose: auto-action and watchdog notices 1 hour, a thank-you
for a donation 24 hours, the notice of a new DDC version 7 days, the
scheduled donation reminder for good. On top: the player warning goes
shortly after its action, a bulk summary after 5 minutes.

WHY NOT discord's delete_after: that is a timer in the running process. A
restart of DDC lost it, and the channel cleanup that runs at start and when
an overview is posted anew deleted the reminder that was meant to stay,
while it spared the auto-action notices for good.

THE CONTRACT: a public post goes through message_lifetimes.post, which
writes its expiry into config/message_lifetimes.json; sweep() deletes what
has expired, also after a restart; the channel cleanup spares what may
still live. The inventory test keeps every raw send in cogs/ and services/
on a short list of posts that are meant to stay (the overviews, the
translations, the replies to a command).

HOW THIS TEST CAN FAIL: a post loses its lifetime, a restart forgets one,
the cleanup takes the reminder, or a new raw send appears.

COUNTER-CHECK (2026-10-01): red before the change (no module, no records,
six raw sends outside the list).
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT = Path(__file__).resolve().parents[2]


class _Message:
    def __init__(self, channel, message_id):
        self.channel, self.id = channel, message_id


class _Channel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.sent, self.deleted = [], []

    async def send(self, *args, **kwargs):
        message = _Message(self, 1000 + len(self.sent))
        self.sent.append((args, kwargs, message))
        return message

    def get_partial_message(self, message_id):
        channel = self

        class _Partial:
            async def delete(self):
                channel.deleted.append(message_id)
        return _Partial()


@pytest.fixture
def lifetimes(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    import services.discord.message_lifetimes as module
    clock = [1_000_000.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    return module, clock


def _bot(*channels):
    by_id = {channel.id: channel for channel in channels}
    return SimpleNamespace(get_channel=lambda channel_id: by_id.get(int(channel_id)))


def test_the_chosen_lifetimes():
    from services.discord.message_lifetimes import LIFETIMES
    assert LIFETIMES == {"auto_action": 3600, "donation_thanks": 24 * 3600,
                         "update_notice": 7 * 24 * 3600, "donation_reminder": None,
                         "bulk_summary": 300, "player_warning": None}


@pytest.mark.asyncio
async def test_a_post_expires_and_is_swept_even_after_a_restart(lifetimes):
    module, clock = lifetimes
    channel = _Channel(111)
    await module.post(channel, "auto_action", "⚡ RESTART Icarus")
    clock[0] += 3599
    await module.sweep(_bot(channel))
    assert channel.deleted == []
    clock[0] += 2
    # A restart: nothing in memory, only the file
    import importlib
    restarted = importlib.reload(module)       # time.time stays patched by the fixture
    await restarted.sweep(_bot(channel))
    assert channel.deleted == [1000]
    await restarted.sweep(_bot(channel))
    assert channel.deleted == [1000], "deleted twice - the record was not dropped"


@pytest.mark.asyncio
async def test_a_warning_lives_as_long_as_it_is_given(lifetimes):
    module, clock = lifetimes
    channel = _Channel(111)
    await module.post(channel, "player_warning", "Valheim restarts in 10 minutes", lifetime=25 * 60)
    clock[0] += 25 * 60 + 1
    await module.sweep(_bot(channel))
    assert channel.deleted == [1000]


@pytest.mark.asyncio
async def test_the_cleanup_spares_what_may_live(lifetimes):
    module, clock = lifetimes
    channel = _Channel(111)
    await module.post(channel, "donation_reminder", "Support DDC")
    await module.post(channel, "donation_thanks", "Thank you, Anna")
    clock[0] += 25 * 3600                       # the thank-you has expired, the reminder never does
    assert module.alive_ids() == {1000}


def test_no_raw_public_send_outside_the_list():
    """Every send to a channel in cogs/ and services/ is either a lifetime post or meant to stay."""
    meant_to_stay = {
        "cogs/channel_lifecycle.py",          # the status and control overviews
        "cogs/message_updates.py",            # the overviews, posted anew
        "cogs/slash_commands.py",             # /ss and the other answers to a command
        "cogs/player_joins.py",               # delete_after: never spared by the cleanup
        "services/translation/translation_service.py",   # translated posts are content
        "services/discord/message_lifetimes.py",         # the one place that posts with a lifetime
    }
    send = re.compile(r"\bawait [a-z_]*channel\.send\(")
    raw = []
    for directory in ("cogs", "services"):
        for path in sorted((PROJECT / directory).rglob("*.py")):
            rel = str(path.relative_to(PROJECT))
            if rel in meant_to_stay:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if send.search(line):
                    raw.append(f"{rel}:{number}: {line.strip()}")
    assert raw == [], "a public post without a lifetime:\n" + "\n".join(raw)


# --- at the call sites -------------------------------------------------------------------

def _records(tmp_path):
    import json
    return json.loads((tmp_path / "message_lifetimes.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_an_auto_action_notice_stays_an_hour(lifetimes, tmp_path):
    module, clock = lifetimes
    from services.automation.automation_service import AutomationService
    channel = _Channel(222)
    service = AutomationService.__new__(AutomationService)
    assert await service._send_feedback(_bot(channel), 222, "⚡ `RESTART` **Icarus** — *Watch*") is True
    assert _records(tmp_path) == {"222:1000": clock[0] + 3600}


@pytest.mark.asyncio
async def test_a_player_warning_stays_until_after_its_action(lifetimes, tmp_path, monkeypatch):
    module, clock = lifetimes
    from services.scheduling import player_gate
    channel = _Channel(333)
    monkeypatch.setattr("services.config.config_service.load_config", lambda: {})
    monkeypatch.setattr(player_gate, "warning_channel_ids", lambda config: [333])
    await player_gate.post_warning(_bot(channel), "Valheim restarts in 10 minutes",
                                   stays_for=player_gate.warning_lifetime(10))
    assert _records(tmp_path) == {"333:1000": clock[0] + 10 * 60 + 15 * 60}


@pytest.mark.asyncio
async def test_the_channel_cleanup_spares_the_reminder_and_takes_the_rest(lifetimes):
    module, clock = lifetimes
    from services.discord.channel_cleanup_service import ChannelCleanupService
    channel = _Channel(111)
    reminder = await module.post(channel, "donation_reminder", "Support DDC")
    bot_user = object()
    service = ChannelCleanupService.__new__(ChannelCleanupService)
    service.bot = SimpleNamespace(user=bot_user)
    asked = []

    async def cleanup_channel(request):
        asked.append(request)
    service.cleanup_channel = cleanup_channel
    await service.delete_bot_messages_preserve_live_logs(channel, "start")

    spared = asked[0].custom_filter

    def _bot_message(message_id):
        return SimpleNamespace(id=message_id, author=bot_user, embeds=[], content="")
    assert spared(_bot_message(reminder.id)) is False, "the reminder was deleted"
    assert spared(_bot_message(4242)) is True, "an old bot message was spared"
