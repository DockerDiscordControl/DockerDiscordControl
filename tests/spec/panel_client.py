# -*- coding: utf-8 -*-
"""A logged-in test client of the web panel, on a throwaway config directory.

Shared by the stage 4 route findings (section 32, 2026-09-30); the harness is
the one of test_spam_settings_are_checked_by_the_server.py without its
spam-service stub.
"""

import base64
import json

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "a-long-enough-panel-password"


def basic_auth():
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()}


@pytest.fixture
def panel(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.json").write_text(json.dumps({"language": "en"}))
    (config / "tasks.json").write_text("[]")
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config))
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.delenv("DDC_TLS_MODE", raising=False)

    import app.auth as auth_module
    from app.auth import auth_limiter, clear_credential_cache
    from app.web import create_app

    hashed = generate_password_hash(PASSWORD)
    monkeypatch.setattr(auth_module, "load_config",
                        lambda: {"web_ui_user": "admin", "web_ui_password_hash": hashed})
    auth_limiter.ip_dict.clear()
    clear_credential_cache()
    yield create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})
    auth_limiter.ip_dict.clear()
