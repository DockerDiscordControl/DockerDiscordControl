# -*- coding: utf-8 -*-
"""The mech story finds every chapter in every language it ships.

THE FINDING (stage 4 review before v3.1.0, a side finding of the section 03
verifier): the parser recognised a chapter by the start of its header,
"Chapter I:" or "Kapitel I:". The French file writes "Prologue I : ..." with
a space before the colon, as French does, so neither prologue nor the
epilogue was found; and "Chapitre I" (without the colon) also matched
"Chapitre II", "III", "IV" and "IX", "Chapitre V" matched "VI" to "VIII". A
French bot showed the wrong chapter or none.

THE CONTRACT: each shipped story file yields the two prologues, nine
chapters and the epilogue, each under its own key and starting with its own
header.

HOW THIS TEST CAN FAIL: a language loses a chapter, or one chapter's text
lands under another's key.

COUNTER-CHECK (2026-09-29): French red before the change; English and
German green before and after.
"""

import re
from pathlib import Path

import pytest

from services.mech.mech_story_service import MechStoryService

STORIES = Path(__file__).resolve().parents[2] / "services" / "mech" / "defaults" / "stories"
KEYS = ["prologue1", "prologue2"] + [f"chapter{n}" for n in range(1, 10)] + ["epilogue"]
ROMAN = ["I", "II", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", None]


@pytest.mark.parametrize("language", ["en", "de", "fr"])
def test_every_chapter_is_found_under_its_own_key(language):
    text = (STORIES / f"{language}.txt").read_text(encoding="utf-8")
    chapters = MechStoryService._parse_story_file(object.__new__(MechStoryService), text)
    assert sorted(chapters) == sorted(KEYS), f"{language}: found {sorted(chapters)}"
    for key, numeral in zip(KEYS, ROMAN):
        header = chapters[key].split("\n", 1)[0]
        if numeral is not None:
            assert re.match(rf"^\S+ {numeral}\s*:", header), f"{language} {key} starts with {header!r}"
