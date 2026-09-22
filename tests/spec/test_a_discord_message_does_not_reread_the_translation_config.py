# -*- coding: utf-8 -*-
"""Every message on the server must not cost a file read.

THE FINDING (review E32, services/translation/translation_config_service.py):
``TranslationMonitor.on_message`` is a listener on **every message in every
channel the bot can see**. It hands each one to
``TranslationService.process_message``, which starts:

    settings = self.config_service.get_settings()          # -> _load_config_file()
    source_ids = self.config_service.get_source_channel_ids()   # -> _load_config_file()
    if context.channel_id not in source_ids:
        return []

and ``_load_config_file`` has no cache at all - it opens and JSON-parses
``config/channel_translations.json`` every single time.

Measured in the running container, on a channel that is not a translation
source at all:

    process_message: 0.20 ms per message, 2.0 file reads per message

So every message anybody writes anywhere on the server made DDC open and parse
a config file twice, on a bind-mounted filesystem, to find out the message had
nothing to do with it.

This is the same sentence as review E30 - a configuration read on a path that
runs per item rather than per operation - and it has the same answer. The file
is cached and the cache is keyed on the file's mtime, so an edit in the web
panel or by hand is picked up on the next call and nothing needs invalidating
by hand.
"""

import json
import time

import pytest


@pytest.fixture
def service(tmp_path, monkeypatch):
    from services.translation.translation_config_service import TranslationConfigService

    config_file = tmp_path / "channel_translations.json"
    config_file.write_text(json.dumps({
        "settings": {"enabled": True},
        "channel_pairs": [],
    }))

    instance = TranslationConfigService.__new__(TranslationConfigService)
    instance.config_file = config_file
    for name in ("_lock", "_config_lock"):
        if not hasattr(instance, name):
            import threading
            setattr(instance, name, threading.RLock())
    return instance


def _count_reads(instance, monkeypatch):
    reads = {"n": 0}
    real_open = open

    def counting_open(path, *a, **kw):
        if str(path) == str(instance.config_file):
            reads["n"] += 1
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", counting_open)
    return reads


def test_repeated_reads_hit_the_file_once(service, monkeypatch):
    reads = _count_reads(service, monkeypatch)

    for _ in range(50):
        service.get_settings()

    assert reads["n"] <= 1, (
        f"50 messages cost {reads['n']} reads of channel_translations.json; "
        f"this runs for every message on the whole server"
    )


def test_a_changed_file_is_picked_up(service, monkeypatch):
    assert service.get_settings().enabled is True

    time.sleep(0.02)
    service.config_file.write_text(json.dumps({
        "settings": {"enabled": False},
        "channel_pairs": [],
    }))

    assert service.get_settings().enabled is False, (
        "the translation settings were changed and DDC kept the old ones - a "
        "cache that never notices is worse than no cache"
    )


def test_the_content_is_still_right(service):
    """Counter-check: caching must not change the answer."""
    settings = service.get_settings()
    assert settings.enabled is True


def test_an_unreadable_file_still_falls_back(service, monkeypatch):
    """Counter-check: the error path must survive the cache."""
    service.config_file.write_text("{ not json")

    settings = service.get_settings()
    assert settings is not None, "a corrupt file raised instead of falling back"


def test_a_caller_cannot_corrupt_the_cache(service, monkeypatch):
    """Every write path loads, mutates and saves - so the cache must be copied.

    Handing out the cached object would let a save that FAILED leave its change
    in memory, and DDC would go on believing something that is not on disk.
    """
    first = service._load_config_file()
    first["settings"]["enabled"] = False
    first["channel_pairs"].append({"poisoned": True})

    second = service._load_config_file()

    assert second["settings"]["enabled"] is True, (
        "a caller's change leaked into the cache; a failed save would leave "
        "DDC believing a setting that never reached the disk"
    )
    assert second["channel_pairs"] == [], "a caller's append leaked into the cache"
