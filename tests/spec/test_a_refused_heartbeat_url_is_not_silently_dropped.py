# -*- coding: utf-8 -*-
"""A heartbeat URL that is refused is said out loud, not silently emptied.

THE FINDING: the Status Watchdog's ping URL is kept only when it starts with
https://. Anything else - the http:// address of a LAN Uptime Kuma, the most
likely thing an operator types - is replaced by an empty, disabled heartbeat.
The save then reports "Configuration saved successfully", and the field is
blank after the reload; the operator concludes the panel lost their input,
and nothing says the URL was refused on purpose. The browser's
pattern="https://.*" never fires either: the save is a click handler that
posts by AJAX and never calls checkValidity().

The policy stays - a heartbeat carries a secret path and belongs on HTTPS -
but the answer now says what happened.

COUNTER-CHECK (2026-09-22): red before - the save said nothing; an https URL
and an empty field must stay quiet (second and third test).
"""

import pytest

from services.config.config_form_parser_service import ConfigFormParserService


def _message(form):
    class _Service:
        def get_config(self, force_reload=False):
            return {}

        def save_config(self, config):
            return type("R", (), {"success": True, "message": "Configuration saved"})()

    _config, success, message = ConfigFormParserService.process_config_form(form, {}, _Service())
    assert success is True
    return message


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(ConfigFormParserService, "_save_channel_permissions",
                        staticmethod(lambda *a, **kw: True))


def test_an_http_url_is_reported():
    message = _message({"heartbeat_ping_url": "http://192.168.1.50/api/push/abc",
                        "enableHeartbeatSection": "1"})

    assert "https" in message.lower() and "heartbeat" in message.lower(), message


def test_an_https_url_says_nothing():
    """Counter-check: the ordinary case must stay quiet."""
    message = _message({"heartbeat_ping_url": "https://hc.example.com/ping/abc",
                        "enableHeartbeatSection": "1"})

    assert "heartbeat" not in message.lower(), message


def test_an_empty_field_says_nothing():
    """Counter-check: no heartbeat at all is not a mistake."""
    assert "heartbeat" not in _message({"heartbeat_ping_url": ""}).lower()
