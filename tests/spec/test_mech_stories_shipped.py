# -*- coding: utf-8 -*-
"""The mech stories must be present on every installation - in the bot's
language.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision. The work is decided: "ship it".

THE FINDING, IN TWO PARTS.

1. ``config/mech/stories/{de,en,fr}.txt`` only existed on the operator's
   server (never in the repository, not in the image). On every fresh install
   ``MechStoryService`` returns ``{}``, and the story button answers on
   EVERY level "No story chapter available for this mech yet."
2. Where the files exist, every server got the GERMAN version:
   ``get_all_chapters()`` defaults to ``'de'``, and
   ``MechHistoryButton._load_epic_story_chapters`` (story button AND
   history view) passes no language.

THE FIX: the three files are shipped as defaults in
``services/mech/defaults/stories/`` (byte for byte from the operator's server,
checksum compared). A file under ``<config dir>/mech/stories/`` wins. The
fallback applies ONLY when no directory is passed explicitly - whoever passes
one (tests) still gets exactly that one. The callers pass the bot language;
for languages other than de/en/fr the service falls back to English as before.
"""

from unittest.mock import MagicMock, patch

import pytest

from cogs.control_ui import MechHistoryButton
from cogs.translation_manager import translation_manager
from services.mech.mech_story_service import MechStoryService, get_mech_story_service


@pytest.fixture
def fresh_install(tmp_path, monkeypatch):
    target = tmp_path / "empty_config"
    target.mkdir()
    monkeypatch.setenv("DDC_CONFIG_DIR", str(target))
    get_mech_story_service().clear_cache()
    try:
        yield target
    finally:
        get_mech_story_service().clear_cache()


def test_a_fresh_install_has_stories(fresh_install):
    """THE FINDING, first part."""
    chapters = MechStoryService().get_all_chapters("en")
    assert "prologue1" in chapters and "chapter1" in chapters and "epilogue" in chapters, (
        f"A fresh install has no mech stories: {sorted(chapters)}"
    )


def test_the_languages_differ(fresh_install):
    """Guard: otherwise the language test below would prove nothing."""
    service = MechStoryService()
    assert service.get_all_chapters("de")["chapter1"] != service.get_all_chapters("en")["chapter1"]


def test_the_own_story_wins(fresh_install):
    """Boundary: the operator's override stays effective."""
    (fresh_install / "mech" / "stories").mkdir(parents=True)
    (fresh_install / "mech" / "stories" / "en.txt").write_text(
        "Title\n\nChapter I: Own\nOwn text.", encoding="utf-8")

    assert "Own text." in MechStoryService().get_all_chapters("en")["chapter1"]


def test_a_passed_directory_does_not_fall_back(tmp_path):
    """Boundary: whoever passes a directory gets exactly that one."""
    assert MechStoryService(story_dir=str(tmp_path)).get_all_chapters("en") == {}


def test_the_story_button_speaks_the_bot_language(fresh_install):
    """THE FINDING, second part: so far always 'de'."""
    expected = MechStoryService().get_all_chapters("en")
    assert expected, "Without shipped stories this test would prove nothing."

    with patch.object(translation_manager, "get_current_language", return_value="en"):
        loaded = MechHistoryButton(MagicMock(), 1)._load_epic_story_chapters()

    assert loaded == expected, (
        "The story button does not load the story in the bot's language (en)."
    )
