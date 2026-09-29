# -*- coding: utf-8 -*-
"""The 🎵 song link stays while it plays.

THE FINDING (stage 4 review before v3.1.0, section 03 pass 4 F5, verified
2026-09-29). PlaySongButton sends the YouTube link, which Discord renders
as an embedded player - with delete_after=NOTICE_STAYS_FOR (15 s). The
sweep that gave every one-off notice its delete_after (4bcdd155) caught it
too: the player vanished fifteen seconds into the song.

THE CONTRACT: the song link is sent without delete_after (it is something
to use, like a panel); the error notice keeps its delete_after. The
notice-sweep guard names this one exemption.

HOW THIS TEST CAN FAIL: the link gets a delete_after again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


def test_the_song_link_is_not_timed_out(monkeypatch):
    from cogs import mech_ui

    monkeypatch.setattr(mech_ui, "is_donations_disabled", lambda: False)
    monkeypatch.setattr(mech_ui, "_mech_button_braked", AsyncMock(return_value=False))
    monkeypatch.setattr("services.web.mech_music_service.get_mech_music_service",
                        lambda: SimpleNamespace(get_mech_music_url=lambda req: SimpleNamespace(
                            success=True, title="T", url="https://youtu.be/x", error=None)))
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    asyncio.run(mech_ui.PlaySongButton(MagicMock(), 3).callback(interaction))

    call = interaction.followup.send.await_args
    assert "https://youtu.be/x" in call.args[0]
    assert "delete_after" not in call.kwargs, "the player disappears mid-song"
