# -*- coding: utf-8 -*-
"""An empty translation is treated as a gap, and that is the decision.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 10 F3) is REFUTED, and this
test is what the refutation rests on. The report said ``translate()`` asks
``if result:`` and therefore cannot return a translation that is
deliberately empty - a label suppressed in one language falls through to
English instead.

Measured on 2026-09-20: of 65,040 entries in the 41 catalogues, not one is
an empty string. Nothing in this product uses "" to suppress a label. What
an empty value would really mean here is a translation gap - and then
falling back to English is the better answer: a label that renders as
nothing tells the user less than an English one, and an empty embed field
name is not something Discord accepts.

So the behaviour stays, and the catalogues are scanned so the premise of
this decision cannot quietly stop being true.
"""

import json
from pathlib import Path

from cogs.translation_manager import TranslationManager

PROJECT = Path(__file__).resolve().parents[2]
LOCALES = PROJECT / "locales"


def _manager(translations):
    """A manager of one's own - object.__new__, not TranslationManager.__new__.

    TranslationManager is a singleton: its __new__ creates the ONE instance and
    stores it on the class, so building a "fresh" one that way hands back the
    global translator, and setting _translations on it takes the catalogues away
    from every later caller. Measured the hard way: it turned three tests in
    another file English.
    """
    manager = object.__new__(TranslationManager)
    manager._translations = translations
    manager._current_language = "de"
    return manager


def test_a_real_translation_is_used():
    """Premise: the lookup works at all."""
    manager = _manager({"de": {"Start": "Starten"}, "en": {"Start": "Start"}})

    assert manager.translate("Start", "de") == "Starten"


def test_a_missing_key_falls_back_to_english():
    manager = _manager({"de": {}, "en": {"Start": "Start"}})

    assert manager.translate("Start", "de") == "Start"


def test_an_empty_translation_falls_back_too():
    """The decision: "" is a gap, not a suppressed label."""
    manager = _manager({"de": {"Start": ""}, "en": {"Start": "Start"}})

    assert manager.translate("Start", "de") == "Start", (
        "an empty German value must not become an empty label"
    )


def test_no_catalogue_uses_an_empty_value():
    """The premise of that decision, measured rather than assumed."""
    empty = {}
    for path in sorted(LOCALES.glob("*.json")):
        catalogue = json.loads(path.read_text(encoding="utf-8"))
        keys = [key for key, value in catalogue.items() if value == ""]
        if keys:
            empty[path.name] = keys[:5]

    assert not empty, (
        "a catalogue uses an empty string - decide what it should mean before "
        f"relying on the fallback: {empty}"
    )
