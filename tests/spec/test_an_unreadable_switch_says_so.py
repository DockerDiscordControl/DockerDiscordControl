# -*- coding: utf-8 -*-
"""
THE FINDING (review C10, section 36 F2): `utils/settings.py` says of itself

    A fallback to the environment is LOGGED. The original swallowed the failure
    silently, which is exactly the "values quietly tidied away" pattern this
    programme hunts.
    ...
    Never raises: a broken setting must not take a service down with it. What it
    does instead of raising is say so.

For every type but one it does. `_convert` calls `value_type(raw_value)`, and an
unusable number raises, is caught, and produces the warning
"has the unusable value ... using the default instead". The `bool` branch takes
a different road:

    return str(raw_value).strip().lower() in ('true', '1', 'yes', 'on')

That never raises, so the warning is never reached. A typo - "flase",
"enabled", "ja" - or any value the list does not know becomes False. An
Advanced Setting whose default is True is switched OFF by a typo, with nothing
in the log to say so. That is precisely the pattern the module was written to
remove, left standing in the one branch that cannot raise.

The counter-check (test_the_words_that_are_understood_are_still_understood)
keeps the fix from turning every unknown value into the default: the known
words on both sides must keep meaning what they meant, silently.
"""

import logging

import pytest

from utils import settings as settings_module


@pytest.fixture(autouse=True)
def no_config_service(monkeypatch):
    """Read only from the environment: a config service that offers no
    advanced_settings, so the config path stays quiet and out of the way."""
    class _Config:
        @staticmethod
        def get_config():
            return {}

    import services.config.config_service as config_service
    monkeypatch.setattr(config_service, "get_config_service", lambda: _Config())


def _get(monkeypatch, raw, default, key="DDC_SPEC_SWITCH"):
    monkeypatch.setenv(key, raw)
    return settings_module.get_setting(key, default, bool)


def test_a_misspelled_switch_is_not_silently_off(monkeypatch, caplog):
    """THE FINDING: an unusable value must fall back to the default, loudly."""
    with caplog.at_level(logging.WARNING, logger="ddc.settings"):
        value = _get(monkeypatch, "flase", True)

    assert value is True
    assert any("flase" in r.getMessage() for r in caplog.records)


def test_an_unknown_word_does_not_quietly_mean_off(monkeypatch, caplog):
    """'enabled' is not in the list of true words - but it plainly is not a
    request to switch the setting off either."""
    with caplog.at_level(logging.WARNING, logger="ddc.settings"):
        value = _get(monkeypatch, "enabled", True)

    assert value is True
    assert any("enabled" in r.getMessage() for r in caplog.records)


def test_an_empty_value_falls_back_to_the_default(monkeypatch, caplog):
    """An empty string says nothing about the switch; it must not decide it."""
    with caplog.at_level(logging.WARNING, logger="ddc.settings"):
        value = _get(monkeypatch, "   ", True)

    assert value is True


def test_the_words_that_are_understood_are_still_understood(monkeypatch, caplog):
    """COUNTER-CHECK: the fix must not turn everything into the default. Both
    sides of the switch keep working, and keep quiet about it."""
    with caplog.at_level(logging.WARNING, logger="ddc.settings"):
        for raw in ("true", "1", "YES", "On"):
            assert _get(monkeypatch, raw, False) is True
        for raw in ("false", "0", "No", "OFF"):
            assert _get(monkeypatch, raw, True) is False

    assert [r.getMessage() for r in caplog.records] == []


def test_a_number_that_is_nonsense_still_says_so(monkeypatch, caplog):
    """COUNTER-CHECK: the loud path for the other types is what bool was
    missing - it must still be there."""
    monkeypatch.setenv("DDC_SPEC_NUMBER", "abc")
    with caplog.at_level(logging.WARNING, logger="ddc.settings"):
        value = settings_module.get_setting("DDC_SPEC_NUMBER", 42, int)

    assert value == 42
    assert any("abc" in r.getMessage() for r in caplog.records)
