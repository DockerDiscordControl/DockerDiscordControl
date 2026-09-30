# -*- coding: utf-8 -*-
"""The panel's "Enable background refresh" switch is obeyed at start.

THE FINDING (stage 4 review before v3.1.0, section 34 pass 4): switching
the checkbox off saves advanced_settings.DDC_ENABLE_BACKGROUND_REFRESH =
'0', which web_helpers reads config-first as off - but
register_background_services read only os.environ (unset: on) and started
the refresh worker anyway, for the life of the process.

THE CONTRACT: the start reads the switch the way every other advanced
setting is read (utils.settings.get_setting: config, then environment,
then the default); '0' in the panel means no worker.

HOW THIS TEST CAN FAIL: the worker is started against the panel's '0'
again, or the environment switch stops working.

COUNTER-CHECK (2026-09-30): red before the change (started once).
"""

from types import SimpleNamespace

import pytest
from flask import Flask

import app.web.background as background


@pytest.fixture
def started(monkeypatch):
    calls = []
    monkeypatch.setattr(background, "HAS_GEVENT", False)
    monkeypatch.setattr(background, "start_background_refresh", lambda logger: calls.append("refresh"))
    monkeypatch.setattr(background, "start_mech_decay_background", lambda logger: calls.append("decay"))
    monkeypatch.setattr(background, "load_active_containers_from_config", lambda: [])
    monkeypatch.setattr("app.utils.web_helpers.register_panel_activity", lambda app: None)
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.delenv("DDC_ENABLE_BACKGROUND_REFRESH", raising=False)
    return calls


def _panel_says(monkeypatch, advanced):
    service = SimpleNamespace(get_config=lambda: {"advanced_settings": advanced})
    monkeypatch.setattr("services.config.config_service.get_config_service", lambda: service)


def test_the_panels_off_is_obeyed(started, monkeypatch):
    _panel_says(monkeypatch, {"DDC_ENABLE_BACKGROUND_REFRESH": "0"})
    background.register_background_services(Flask(__name__))
    assert started == []


def test_the_panels_on_and_the_default_still_start_it(started, monkeypatch):
    _panel_says(monkeypatch, {"DDC_ENABLE_BACKGROUND_REFRESH": "1"})
    background.register_background_services(Flask(__name__))
    _panel_says(monkeypatch, {})
    background.register_background_services(Flask(__name__))
    assert started == ["refresh", "refresh"]


def test_the_environment_switch_still_works(started, monkeypatch):
    _panel_says(monkeypatch, {})
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    background.register_background_services(Flask(__name__))
    assert started == []
