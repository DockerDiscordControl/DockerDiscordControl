# -*- coding: utf-8 -*-
"""
THE FINDING (review C20, section 35 F2): `_request_scoped_config` in
`app/web/i18n.py` is called from the i18n context processor on every single
template render. When the configuration cannot be loaded it does

    try:
        config = load_config()
    except Exception:
        config = {}

- no log line at any level, not even DEBUG. The page then renders in English
with default settings, looking perfectly healthy, and there is nothing anywhere
for an operator to find. The panel silently shows the wrong language and the
wrong settings, and the one clue that would explain it is thrown away.

The bare `except Exception` itself is right here: a broken config must not take
the whole panel down. What was missing is that it says so.

The counter-check (test_a_working_config_stays_quiet) keeps the fix from
turning every normal render into a log line.
"""

import logging

import pytest
from flask import Flask

from app.web import i18n as i18n_module


@pytest.fixture
def app_context():
    app = Flask(__name__)
    with app.test_request_context("/"):
        yield


def test_a_config_that_cannot_be_loaded_leaves_a_trace(app_context, monkeypatch, caplog):
    """THE FINDING: the panel may fall back, but not in silence."""
    def _broken():
        raise OSError("config.json unreadable")

    monkeypatch.setattr(i18n_module, "load_config", _broken)

    with caplog.at_level(logging.DEBUG):
        config = i18n_module._request_scoped_config()

    assert config == {}
    assert any("config" in record.getMessage().lower() for record in caplog.records), \
        "the fallback left nothing in the log"


def test_the_page_still_renders_on_a_broken_config(app_context, monkeypatch):
    """The fallback itself stays: a broken config must not take the panel
    down."""
    monkeypatch.setattr(i18n_module, "load_config",
                        lambda: (_ for _ in ()).throw(ValueError("broken json")))

    assert i18n_module._request_scoped_config() == {}


def test_a_working_config_stays_quiet(app_context, monkeypatch, caplog):
    """COUNTER-CHECK: every normal render must not produce a log line."""
    monkeypatch.setattr(i18n_module, "load_config", lambda: {'ui_language': 'de'})

    with caplog.at_level(logging.DEBUG):
        config = i18n_module._request_scoped_config()

    assert config == {'ui_language': 'de'}
    assert [r.getMessage() for r in caplog.records
            if r.name.startswith("app.web.i18n")] == []
