# -*- coding: utf-8 -*-
"""The cached embed strings are in the language that was asked for.

THE FINDING (review D15, pass 2, section 14 F5; pass 1 reported the same
thing as 14 F3 and left it in the "not re-checked, all low" bucket):
`get_translations(lang)` keys its cache by `lang` but fills it with `_("...")`
calls, and the module-level `_` asks `translation_manager.get_current_language()`
- the ambient bot language. The argument decided the cache key and nothing
else.

It is not latent. The two sides disagree about the default: status_handlers
reads `current_config.get('language', 'de')` while `get_current_language()`
reads `config.get('language', 'en')` and also answers 'en' whenever
load_config raises. On an installation whose configuration carries no
`language` key, the ENGLISH strings are cached under the key
"translations_de" and stay there - the status embeds show English while the
code believes it asked for German.

`translation_manager.translate(text, lang)` takes the language explicitly and
has the same fallback chain. That is what this cache needs.
"""

import pytest

from cogs.translation_manager import translation_manager
from services.discord.embed_helper_service import EmbedHelperService

KEYS = ("online_text", "offline_text", "cpu_text", "ram_text", "uptime_text")


@pytest.fixture
def helper(monkeypatch):
    """A fresh helper, with the ambient language pinned to English so a
    German answer can only come from the argument."""
    monkeypatch.setattr(translation_manager, "get_current_language", lambda: "en")
    return EmbedHelperService()


def test_two_languages_are_two_answers(helper):
    german = helper.get_translations("de")
    english = helper.get_translations("en")

    assert german != english, (
        f"'de' and 'en' came back identical: {german}"
    )


def test_the_language_asked_for_is_the_one_returned(helper):
    german = helper.get_translations("de")

    expected = {key: translation_manager.translate(source, "de")
                for key, source in (("cpu_text", "CPU"), ("ram_text", "RAM"),
                                    ("uptime_text", "Uptime"),
                                    ("online_text", "**Online**"))}
    for key, value in expected.items():
        assert german[key] == value, (
            f"{key}: asked for German, got {german[key]!r}, German is {value!r}"
        )


def test_it_is_still_a_cache(helper):
    """Counter-check: the second call must not rebuild it."""
    assert helper.get_translations("de") is helper.get_translations("de")


def test_an_unknown_language_still_answers(helper):
    """Counter-check: a language with no catalogue falls back, it does not
    fail - the same chain translate() already applies."""
    answer = helper.get_translations("xx")

    assert set(KEYS) <= set(answer)
    assert all(isinstance(value, str) and value for value in answer.values())
