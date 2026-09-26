# -*- coding: utf-8 -*-
"""The /donate panel stays tracked until the restart clean-up can find it.

THE FINDING (audit 2026-09-26). a5c4b232 (2026-09-23) remembers the id of the
panel /donate posts, under the key 'donation' beside a channel's overview ids,
so that a restart inside its ~15 minutes deletes it instead of leaving a
button that does nothing. The periodic edit loop and the status-channel
sender, both older than that key, treated every key other than 'overview' and
'admin_overview' as a leftover per-container entry:

  * the loop deleted 'donation' within a minute, with a WARNING about a
    "phantom individual server entry", and the next persist wrote the map
    without it - so the restart clean-up found nothing to delete;
  * the status-channel sender cleared the whole map before posting;
  * and a channel holding nothing but a donation id counted as a channel DDC
    had built, so the hot-reload's promised retry for a channel whose first
    post had failed never came.

THE CONTRACT: 'donation' is a tracked kind the loop leaves alone, a fresh
overview does not wipe, and a donation id alone does not make a channel "built".

HOW THIS TEST CAN FAIL: the donation id disappears on a loop cycle or a new
overview, or a channel with only a donation id is taken as set up.

COUNTER-CHECK (2026-09-26): red before the fix - the loop cycle removed the
key, and the hot-reload treated channel 222 (donation only) as present.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


@pytest.fixture
def cog(monkeypatch):
    import cogs.message_updates as message_updates
    from cogs.docker_control import DockerControlCog

    monkeypatch.setattr(message_updates, "load_config", lambda: {
        "channel_permissions": {"111": {"enable_auto_refresh": True, "update_interval_minutes": 60}}})
    import services.discord.status_overview_service as overview_service

    monkeypatch.setattr(overview_service, "get_status_overview_service",
                        lambda: SimpleNamespace(make_update_decision=lambda **_: SimpleNamespace(
                            should_update=False, skip_reason="not due", reason="")))

    cog = DockerControlCog.__new__(DockerControlCog)
    cog.initial_messages_sent = True
    cog.channel_server_message_ids = {111: {"overview": 9001, "donation": 9003}}
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    cog.last_message_update_time = {111: {"overview": now}}
    cog.last_channel_activity = {}

    async def _update(*_args):
        return None

    cog._update_overview_message = _update
    return cog


@pytest.mark.asyncio
async def test_a_loop_cycle_keeps_the_donation_id(cog):
    from cogs.docker_control import DockerControlCog

    await DockerControlCog.periodic_message_edit_loop.coro(cog)

    assert cog.channel_server_message_ids[111].get("donation") == 9003, (
        cog.channel_server_message_ids)
    assert cog.channel_server_message_ids[111].get("overview") == 9001


def test_a_donation_id_alone_is_not_a_built_channel():
    from cogs.control_helpers import channel_was_built

    assert channel_was_built({"donation": 1}) is False
    assert channel_was_built({}) is False
    assert channel_was_built({"overview": 1, "donation": 2}) is True
    assert channel_was_built({"admin_overview": 1}) is True


def test_the_hot_reload_and_the_setup_ask_the_same_question():
    """Call sites, read from the source: both places that decide whether a
    channel was built ask channel_was_built, and the status-channel sender
    no longer wipes the map before it posts."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "cogs" / "channel_lifecycle.py").read_text(
        encoding="utf-8")

    assert source.count("channel_was_built(") >= 2, "a site still decides on its own"
    assert "self.channel_server_message_ids[channel.id].clear()" not in source
