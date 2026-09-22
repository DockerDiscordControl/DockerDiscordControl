# -*- coding: utf-8 -*-
"""A level that has no chapter gets no chapter, not somebody else's.

THE FINDING (review C72, section 23 F6): ``_get_chapter_key_for_level`` ends
with ``level_mapping.get(level, "prologue1")``, so it never returns a falsy
key - not for level 0, not for a negative level, not for anything above 11.
``get_story_chapter`` has a guard right above its lookup:

    chapter_key = self._get_chapter_key_for_level(level)
    if not chapter_key:
        return None

That guard could never run. Its own docstring says "Mech level (1-11)" and
"Story text or None if not found", and what actually happened for a level
outside that range was the level-1 prologue, handed out as if it belonged to
that level. A wrong chapter reads like the right one; no chapter does not.
"""

import pytest

from services.mech.mech_story_service import MechStoryService

STORY = {"prologue1": "The dying light.", "chapter9": "The prayer."}


@pytest.fixture
def service(tmp_path, monkeypatch):
    service = MechStoryService(story_dir=str(tmp_path))
    monkeypatch.setattr(service, "_get_story_content", lambda language: dict(STORY))
    return service


@pytest.mark.parametrize("level", [0, -1, 12, 999])
def test_a_level_outside_the_range_has_no_key(service, level):
    assert service.get_chapter_key_for_level(level) is None, (
        f"level {level} is handed the level-1 prologue as if it were its own"
    )


@pytest.mark.parametrize("level", [0, -1, 12, 999])
def test_a_level_outside_the_range_has_no_story(service, level):
    assert service.get_story_chapter(level) is None


def test_the_first_level_still_has_its_prologue(service):
    """Counter-check: prologue1 is a real chapter, and level 1 owns it."""
    assert service.get_chapter_key_for_level(1) == "prologue1"
    assert service.get_story_chapter(1, language="en") == "The dying light."


def test_the_last_level_still_has_its_chapter(service):
    """Counter-check: the other end of the range."""
    assert service.get_chapter_key_for_level(11) == "chapter9"


def test_a_level_with_no_text_yet_is_still_a_level(service):
    """Counter-check: a known level whose text is missing is not the same as
    an unknown level - the key exists, only the content does not."""
    assert service.get_chapter_key_for_level(5) == "chapter3"
    assert service.get_story_chapter(5) is None
