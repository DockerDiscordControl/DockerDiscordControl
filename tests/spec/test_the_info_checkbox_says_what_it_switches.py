# -*- coding: utf-8 -*-
"""The container form's info checkbox says what it switches.

THE FINDING (operator, 2026-09-29, with a screenshot of the container
modal): the checkbox still read "Enable Info Button" / "Info-Button
aktivieren" - but since v3.1.0 every container has an info display, whether
the box is ticked or not. What the box (info.enabled) still decides is
whether the container's OWN text and address are shown in it
(cogs/status_info_integration.py and cogs/control_ui.py read it for exactly
that).

THE CONTRACT: in English and German the label names the own text and
address; no language that wrote "button" (or "bouton") still does. Languages
with their own word for button are not caught by the second check - all 40
were rewritten in the same commit.

HOW THIS TEST CAN FAIL: the old label comes back in some language.

COUNTER-CHECK (2026-09-29): all cases red before the change.
"""

import json
from pathlib import Path

import pytest

LOCALES = Path(__file__).resolve().parents[2] / "locales"
KEY = "web.server.enable_info_btn"
OLD = {"en": "Enable Info Button", "de": "Info-Button aktivieren"}


def _label(language):
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))[KEY]


@pytest.mark.parametrize("language,words", [("en", ("text", "address")),
                                            ("de", ("Text", "Adresse"))])
def test_the_label_names_the_own_text_and_address(language, words):
    label = _label(language)
    assert all(word in label for word in words), f"{language}: {label!r}"


def test_no_language_still_offers_an_info_button():
    before = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    assert before[KEY] != OLD["en"]
    stale = [path.stem for path in sorted(LOCALES.glob("*.json")) if path.stem != "meta"
             if "button" in json.loads(path.read_text(encoding="utf-8"))[KEY].lower()
             or "bouton" in json.loads(path.read_text(encoding="utf-8"))[KEY].lower()]
    assert not stale, f"still an 'info button' in: {stale}"
