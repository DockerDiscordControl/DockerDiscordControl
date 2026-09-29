# -*- coding: utf-8 -*-
"""The mech story's chapter title is in the language of the chapter.

THE FINDING (stage 4 review before v3.1.0, section 03 pass 4 F6): the story
embed took its title from a hard-coded English table, while the chapter text
is in the bot's language - a German reader saw "Prologue I: The Dying Light"
above "Prolog I: Das sterbende Licht".

THE CONTRACT: the title is the chapter's own first line (its header, in its
language); the text below it is the rest.

HOW THIS TEST CAN FAIL: the English title comes back, or the header is shown
twice.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cogs.mech_ui as mech_ui
from services.mech.mech_story_service import MechStoryService

STORIES = Path(__file__).resolve().parents[2] / "services" / "mech" / "defaults" / "stories"


async def test_a_german_chapter_has_a_german_title(monkeypatch):
    chapters = MechStoryService._parse_story_file(
        object.__new__(MechStoryService), (STORIES / "de.txt").read_text(encoding="utf-8"))
    monkeypatch.setattr(mech_ui.MechHistoryButton, "_load_epic_story_chapters",
                        lambda self: chapters)
    monkeypatch.setattr(mech_ui, "is_donations_disabled", lambda: False)
    monkeypatch.setattr(mech_ui, "_mech_button_braked", AsyncMock(return_value=False))
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()

    await mech_ui.ReadStoryButton(SimpleNamespace(), 1).callback(inter)

    embed = inter.followup.send.await_args.kwargs["embed"]
    assert embed.title.startswith("Prolog I"), embed.title
    assert not (embed.description or "").startswith("Prolog I"), "the header is shown twice"
