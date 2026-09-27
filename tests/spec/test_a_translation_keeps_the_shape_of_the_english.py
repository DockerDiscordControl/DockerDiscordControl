# -*- coding: utf-8 -*-
"""A translation keeps the shape of the English: its breaks, emoji, markup and links.

WHY (2026-09-27): about 8,600 strings in 38 languages were still English, and
they were translated in one go. Placeholders already have their guard
(test_every_translation_can_be_formatted.py); this is the rest of what a
translation must not change, because code and Discord depend on it:

* leading and trailing whitespace and line breaks - messages are glued
  together ("\\nNot checked: ..."), and a lost break runs two lines into one;
* a leading emoji - it is the message's status mark (✅ ❌ ⚠️ 🔧);
* ``**`` and backticks - an odd number leaves Discord's markdown open;
* HTML tags in panel strings - the page renders them;
* the project's own links (ddc.bot, GitHub, Discord, PayPal, Buy Me a Coffee).

What it does NOT hold: an emoji a language moves to the front because of its
word order (Japanese "❌ボタン..." for "Click the ❌ button"), and example
addresses a translator localises ("votre-uptime-kuma.com").

COUNTER-CHECK (2026-09-27): green on the catalogues as they were, which is the
point - it is the fence for the mass translation. Sabotage: dropping the
leading "\\n" of one German string, or one "**", turns it red naming the key.
"""

import json
import re
import unicodedata
from pathlib import Path

import pytest

LOCALES = Path(__file__).resolve().parents[2] / "locales"
ENGLISH = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
OWN_HOSTS = ("ddc.bot", "github.com", "discord.com", "discord.gg", "paypal", "buymeacoffee")
TAG = re.compile(r"</?(?:a|b|i|em|strong|code|br|span|small|kbd|ul|li|p)\b[^>]*>")
URL = re.compile(r"https?://[\w.-]+\.[a-z]{2,}[^\s)\]]*")


def _leading_emoji(text):
    stripped = text.lstrip()
    return stripped[0] if stripped and unicodedata.category(stripped[0]) == "So" else ""


def _shape(english, text):
    shape = {
        "leading whitespace": re.match(r"^\s*", text).group(0),
        "trailing whitespace": re.search(r"\s*$", text).group(0),
        "** count": text.count("**"),
        "backtick count": text.count("`"),
        "HTML tags": sorted(TAG.findall(text)),
        "own links": sorted(u for u in URL.findall(text) if any(h in u for h in OWN_HOSTS)),
    }
    if _leading_emoji(english):
        shape["leading emoji"] = _leading_emoji(text)
    return shape


def _languages():
    return sorted(p.stem for p in LOCALES.glob("*.json") if p.stem not in ("en", "meta"))


@pytest.mark.parametrize("language", _languages())
def test_every_translation_keeps_the_english_shape(language):
    catalogue = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))
    broken = []
    for key, text in catalogue.items():
        english = ENGLISH.get(key)
        if not isinstance(english, str) or not isinstance(text, str):
            continue
        want, got = _shape(english, english), _shape(english, text)
        for field in want:
            if want[field] != got[field]:
                broken.append(f"{key[:60]!r}: {field} {want[field]!r} -> {got[field]!r}")
    assert not broken, f"{language}: {len(broken)} broken\n" + "\n".join(broken[:20])
