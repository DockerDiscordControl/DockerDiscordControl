# -*- coding: utf-8 -*-
"""An auto-action notice is spared by the channel cleanup only while its hour runs.

THE OBSERVATION (operator, 2026-10-02): in the control channel the "⚡
RESTART ..." notices of June, September and the evening before stayed. They
predate the message lifetimes (live since 2026-10-01 22:40), so none had a
lifetime - and the channel cleanup spared every message that looked like an
auto-action notice ("⚡ ... — *Rule*"), for good, a rule from before the
lifetimes existed.

THE CONTRACT: the cleanup spares a notice the lifetime registry still
counts as alive, and nothing because of how it looks. The next cleanup (at
start, or when the overview moves down) takes the old ones.

HOW THIS TEST CAN FAIL: the pattern rule comes back and old notices stay
for ever, or a notice inside its hour is deleted.

COUNTER-CHECK (2026-10-02): red before the change (the old notice was spared).
"""

from types import SimpleNamespace

import pytest

from tests.spec.test_every_public_message_has_its_lifetime import _Channel, lifetimes  # noqa: F401

BOT = SimpleNamespace(id=1, name="DDC")


def _filter():
    from services.discord.channel_cleanup_service import ChannelCleanupService
    service = ChannelCleanupService.__new__(ChannelCleanupService)
    service.bot = SimpleNamespace(user=BOT)
    asked = []

    async def cleanup_channel(request):
        asked.append(request)
    service.cleanup_channel = cleanup_channel
    return service, asked


def _notice(message_id):
    return SimpleNamespace(id=message_id, author=BOT, embeds=[],
                           content="⚡ `RESTART` **Satisfactory** — *Satisfactory Update Rule* · [Trigger](x)")


@pytest.mark.asyncio
async def test_an_old_notice_goes_and_a_young_one_stays(lifetimes):  # noqa: F811
    module, clock = lifetimes
    young = await module.post(_Channel(111), "auto_action", "⚡ `RESTART` **Icarus** — *Watch*")
    service, asked = _filter()
    await service.delete_bot_messages_preserve_live_logs(SimpleNamespace(id=111), "start")
    deletable = asked[0].custom_filter
    assert deletable(_notice(4242)) is True, "an auto-action notice from June was spared for good"
    assert deletable(_notice(young.id)) is False, "a notice inside its hour was deleted"
