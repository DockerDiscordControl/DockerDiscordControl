# -*- coding: utf-8 -*-
"""The placeholder of the "Enable Info Button" field must say enable, not share.

No ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. The field "☑️ Enable Info Button" (enhanced_info_modal_simple.py)
has the placeholder key "Type 'X' to enable, leave empty to disable". Its
translations in ALL 40 catalogs said "share" - en: "Type 'X' to share, leave
empty to not share", de: "'X' eingeben zum Teilen ..." - since the commit that
introduced the 40 languages (4ad8a86). No field of the dialog is about sharing
("Show IP Address" has its own key), so every user read a wrong hint there.

The protected-information field next to it had the correct enable/disable
translations - under a German source string. The fix merges the two: the
English key carries the correct translations, the German key is gone.

HOW IT IS CHECKED: against the catalogs directly (the source of what a user
reads), for English, German and French. The expected German text is the
former correct translation, written here - not read from the catalog.
"""

import json
from pathlib import Path

import pytest

LOCALES = Path(__file__).resolve().parents[2] / "locales"
KEY = "Type 'X' to enable, leave empty to disable"
EXPECTED = {
    "en": "Type 'X' to enable, leave empty to disable",
    "de": "'X' eingeben zum Aktivieren, leer lassen zum Deaktivieren",  # language data
    "fr": "Tapez 'X' pour activer, laissez vide pour désactiver",
}


@pytest.mark.parametrize("language", sorted(EXPECTED))
def test_the_placeholder_says_enable(language):
    catalog = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))
    assert catalog.get(KEY) == EXPECTED[language], (
        f"{language}: the Enable Info Button placeholder reads {catalog.get(KEY)!r} - "
        "a hint about sharing on a field that enables the button."
    )


def test_no_catalog_keeps_the_german_source_string():
    """The merge must not leave the old German key behind in any catalog."""
    old = "'X' eingeben zum Aktivieren, leer lassen zum Deaktivieren"  # language data
    left = [p.name for p in sorted(LOCALES.glob("*.json"))
            if p.name != "meta.json" and old in json.loads(p.read_text(encoding="utf-8"))]
    assert not left, f"German source string still a key in: {left}"
