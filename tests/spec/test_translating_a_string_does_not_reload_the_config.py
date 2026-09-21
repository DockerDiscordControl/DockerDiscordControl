# -*- coding: utf-8 -*-
"""Translating a string must not re-read the whole configuration.

THE FINDING (review E30, cogs/translation_manager.py): ``_()`` is the function
behind every user-facing string DDC produces - every embed label, every button,
every error message, once per container per line. It calls
``get_current_language()``, which calls ``load_config()``, which returns
``self._config_cache[cache_key].copy()``: **a full copy of the whole
configuration**, to read one key.

Measured in the running container:

    _()           18.1 us per call
    load_config() 16.5 us per call        <- 91% of it
    config: 361 keys, ~19 KB

So DDC deep-copied a 361-key dictionary to find out which language to use, and
did it again for the next label on the same embed.

**This was found because of a regression of my own.** Review E29 added two
``stat`` calls to the cache lookup so that a hand-edited channel file is
noticed. On this install's bind mount those two cost **54 us**, which would
have made ``load_config()`` - and therefore every translated string - about
four times slower. A fix for a rare hand-edit paid for by a 4x slowdown on the
hottest path in the program is a bad trade, and the measurement is what showed
it. The answer is not to revert E29 but to take ``load_config`` out of the hot
path, after which E29 costs nothing that matters.

The language is cached for a few seconds. It is changed in the web panel and
practically never otherwise, and a label that is one language behind for two
seconds is not a thing anyone can see. ``reload_translations`` clears it, so
the hot-reload path stays exact.
"""

import time

import pytest


@pytest.fixture
def manager(monkeypatch):
    import cogs.translation_manager as tm

    calls = {"n": 0}

    def counting_load_config():
        calls["n"] += 1
        return {"language": "de"}

    monkeypatch.setattr(tm, "load_config", counting_load_config)
    instance = tm.translation_manager
    instance._translations.setdefault("de", {})
    instance._translations["de"]["Server Overview"] = "Server-Übersicht"
    # start from a clean cache whatever an earlier test left behind
    if hasattr(instance, "_language_cached_at"):
        instance._language_cached_at = 0.0
    return instance, calls


def test_many_translations_read_the_config_once(manager):
    instance, calls = manager

    for _ in range(50):
        instance._("Server Overview")

    assert calls["n"] <= 2, (
        f"translating 50 strings re-read the whole configuration {calls['n']} "
        f"times - that is a 361-key dict copy per label on an embed"
    )


def test_the_translation_is_still_correct(manager):
    instance, _calls = manager

    assert instance._("Server Overview") == "Server-Übersicht"
    assert instance._("Server Overview") == "Server-Übersicht", (
        "the second call, served from the language cache, gave a different answer"
    )


def test_reloading_translations_forgets_the_language(manager, monkeypatch):
    """Hot-reload must be exact - that is what it is for."""
    instance, calls = manager
    instance._("Server Overview")
    before = calls["n"]

    instance.reload_translations()
    instance._("Server Overview")

    assert calls["n"] > before, (
        "after an explicit reload the language was still served from the cache"
    )


def test_a_changed_language_is_picked_up(manager, monkeypatch):
    """The cache is short, not permanent."""
    import cogs.translation_manager as tm

    instance, _calls = manager
    instance._("Server Overview")

    monkeypatch.setattr(tm, "load_config", lambda: {"language": "en"})
    instance._language_cached_at = 0.0          # as if the window had passed

    assert instance.get_current_language() == "en", (
        "a language changed in the web panel was never picked up"
    )
