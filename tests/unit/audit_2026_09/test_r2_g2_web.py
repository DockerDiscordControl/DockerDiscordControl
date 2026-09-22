# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, release review, package G2 - web, auth, CSRF.

R2-1   a short DDC_ADMIN_PASSWORD is stored (with a warning) instead of leaving setup mode open
R2-2/3/5  session cookie name, SameSite=Lax, no per-request SESSION_COOKIE_SECURE, no SSL-strict
R2-4   CSRF errors carry a machine-readable reason, translated by the client
R2-6   the setup page checks the server's password rule
R1-10  the heartbeat section is part of the config form; its switch is honoured
plus   footer version from DDC_VERSION, quiet shutdown logging
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path

import pytest
from flask import Flask, jsonify, session
from werkzeug.security import check_password_hash

import services.config.config_service as config_service_module
from services.config.config_service import ConfigService

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = PROJECT_ROOT / "app" / "templates"
JS_DIR = PROJECT_ROOT / "app" / "static" / "js"
SAFE_ENV = {"FLASK_SECRET_KEY": "g2-test-secret-key-" + "x" * 32}


def _template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# R2-1
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(ConfigService, "_instance", None)
    svc = ConfigService()
    monkeypatch.setattr(config_service_module, "_config_service_instance", svc)
    (tmp_path / "config.json").write_text(json.dumps({"language": "en", "web_ui_password_hash": None}))
    return svc


def test_short_env_password_is_stored_and_ends_setup_mode(isolated_service, monkeypatch, caplog):
    import app.utils.web_helpers as wh
    from app.auth import verify_password

    monkeypatch.setenv("DDC_ADMIN_PASSWORD", "short1")
    with caplog.at_level(logging.WARNING):
        wh.set_initial_password_from_env()

    stored = isolated_service.get_config(force_reload=True)["web_ui_password_hash"]
    assert stored and check_password_hash(stored, "short1")
    assert any("shorter than 12" in r.getMessage() for r in caplog.records)

    app = Flask(__name__)
    app.secret_key = "t"
    with app.test_request_context():
        assert verify_password("admin", "setup") is None  # bootstrap credential no longer works
        assert verify_password("admin", "short1") == "admin"


def test_form_and_setup_paths_still_require_12_characters(isolated_service):
    with pytest.raises(ValueError):
        config_service_module.change_web_ui_password("short1")
    assert isolated_service.get_config(force_reload=True)["web_ui_password_hash"] is None


# ---------------------------------------------------------------------------
# R2-2 / R2-3 / R2-5
# ---------------------------------------------------------------------------

def test_session_and_csrf_defaults():
    from app.web.config import build_config

    config = build_config(SAFE_ENV)
    assert config["SESSION_COOKIE_NAME"] == "ddc_session"
    assert config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert config["SESSION_COOKIE_SECURE"] is False
    assert config["WTF_CSRF_SSL_STRICT"] is False


@pytest.fixture
def web_app():
    from flask_wtf.csrf import generate_csrf

    from app.web.config import build_config
    from app.web.csrf import install_csrf_protection
    from app.web.security import install_security_handlers

    app = Flask(__name__)
    app.config.update(build_config(SAFE_ENV))
    app.config["TESTING"] = True

    @app.route("/token")
    def token():
        return jsonify(token=generate_csrf())

    @app.route("/save", methods=["POST"])
    def save():
        return jsonify(success=True)

    install_csrf_protection(app)
    install_security_handlers(app)
    return app


def test_https_request_does_not_make_the_cookie_secure_for_everyone(web_app):
    client = web_app.test_client()
    client.get("/token", base_url="https://ddc.example")
    assert web_app.config["SESSION_COOKIE_SECURE"] is False

    resp = web_app.test_client().get("/token")  # plain-HTTP LAN client afterwards
    cookie = resp.headers["Set-Cookie"]
    assert cookie.startswith("ddc_session=")
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie


def test_security_module_no_longer_mutates_app_config():
    source = (PROJECT_ROOT / "app" / "web" / "security.py").read_text(encoding="utf-8")
    assert 'app.config["SESSION_COOKIE_SECURE"] = True' not in source


# ---------------------------------------------------------------------------
# R2-4
# ---------------------------------------------------------------------------

def _post(client, **kwargs):
    return client.post("/save", headers={"Accept": "application/json"}, **kwargs)


def test_csrf_reason_missing_token(web_app):
    body = _post(web_app.test_client(), json={}).get_json()
    assert body["csrf_error"] is True
    assert body["reason"] == "missing"
    assert "reload" in body["error"].lower()


def test_csrf_reason_session_missing(web_app):
    token = web_app.test_client().get("/token").get_json()["token"]
    body = _post(web_app.test_client(), data={"csrf_token": token}).get_json()  # other browser/cookie gone
    assert body["reason"] == "session_missing"
    assert "session cookie" in body["message"]


def test_csrf_reason_invalid(web_app):
    client = web_app.test_client()
    client.get("/token")
    body = _post(client, data={"csrf_token": "not-a-token"}).get_json()
    assert body["reason"] == "invalid"


def test_csrf_reason_mapping():
    from app.web.csrf import csrf_error_reason

    assert csrf_error_reason("The CSRF token has expired.") == "expired"
    assert csrf_error_reason("The CSRF tokens do not match.") == "invalid"
    assert csrf_error_reason("something new") == "invalid"


def test_client_translates_every_csrf_reason():
    from app.web import csrf

    base = _template("_base.html")
    assert "window.ddcServerErrorMessage = function(data, fallback)" in base
    for reason in set(csrf._CSRF_REASONS.values()):
        assert f"{reason}: ['csrf.{reason}'," in base
    assert "tr('csrf.hint'," in base

    scripts = _template("_scripts.html")
    save_fn = scripts[scripts.index("function saveConfigAjax()"):]
    assert "window.ddcServerErrorMessage(errData" in save_fn
    config_ui = (JS_DIR / "config-ui.js").read_text(encoding="utf-8")
    admin_save = config_ui[config_ui.index("function saveAdminUsers()"):]
    assert "window.ddcServerErrorMessage(result" in admin_save[:2500]


# ---------------------------------------------------------------------------
# R2-6
# ---------------------------------------------------------------------------

def test_setup_page_checks_the_server_password_rule():
    setup = _template("setup.html")
    assert "password.length < 6" not in setup
    assert "password.length < 12" in setup
    assert "[/[a-z]/, /[A-Z]/, /\\d/, /[^A-Za-z0-9]/]" in setup
    assert "characterClasses < 3" in setup


# ---------------------------------------------------------------------------
# R1-10
# ---------------------------------------------------------------------------

def test_heartbeat_section_is_inside_the_config_form():
    page = _template("config.html")
    form_start = page.index('<form method="POST" id="config-form">')
    form_end = page.index("</form> {# --- End of form --- #}")
    include = page.index("{% include '_heartbeat_section.html' %}")
    assert form_start < include < form_end
    assert "<form" not in _template("_heartbeat_section.html")


@pytest.mark.parametrize("switch, enabled", [("on", True), ("1", True), ("0", False), (None, True)])
def test_heartbeat_switch_is_honoured(switch, enabled):
    from services.config.config_form_parser_service import ConfigFormParserService

    form = {"heartbeat_ping_url": "https://hc-ping.example/abc", "heartbeat_interval": "7"}
    if switch is not None:
        form["enableHeartbeatSection"] = switch
    result = ConfigFormParserService._parse_heartbeat(form)
    assert result == {"enabled": enabled, "ping_url": "https://hc-ping.example/abc", "interval": 7}


# ---------------------------------------------------------------------------
# Coordinator add-ons: footer version, quiet shutdown logging
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("env_value, shown", [("2.4.0", "v2.4.0"), ("v2.4.0", "v2.4.0"), ("", "")])
def test_footer_version_comes_from_ddc_version(monkeypatch, env_value, shown):
    from app.web.security import install_security_handlers

    monkeypatch.setenv("DDC_VERSION", env_value)
    app = Flask(__name__)
    install_security_handlers(app)
    assert app.jinja_env.globals["ddc_version"] == shown

    base = _template("_base.html")
    assert "{{ ddc_version }}" in base
    assert not re.search(r'id="neon-version">v\d', base)


def test_shutdown_log_is_debug_and_skipped_on_closed_stream(capsys):
    from app.utils.web_helpers import _log_at_shutdown

    logger = logging.getLogger("g2.shutdown.test")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        _log_at_shutdown(logger, "thread did not terminate")
        assert "thread did not terminate" in stream.getvalue()

        stream.close()
        _log_at_shutdown(logger, "after close")
        assert "Logging error" not in capsys.readouterr().err
    finally:
        logger.removeHandler(handler)


def test_stop_helpers_are_quiet_but_still_warn_about_stuck_threads():
    """Level and stream-safety are independent concerns.

    Routine stop messages are debug (they fired on every container stop). A thread that refuses
    to terminate stays a WARNING - it is a real problem and must not be hidden (V2 review). But
    both go through _log_at_shutdown, because these helpers also run from the atexit hook, where
    a direct logger.warning() hits an already closed stream and prints a traceback.
    """
    source = (PROJECT_ROOT / "app" / "utils" / "web_helpers.py").read_text(encoding="utf-8")
    for message in ("Background thread did not terminate within timeout",
                    "Mech decay thread did not terminate within timeout"):
        assert f'_log_at_shutdown(logger, "{message}", logging.WARNING)' in source
        assert f'logger.warning("{message}")' not in source
    # the routine messages keep the default debug level
    assert '_log_at_shutdown(logger, "Stopping background Docker cache refresh thread")' in source


def test_shutdown_helper_honours_the_level_and_still_skips_closed_streams(capsys):
    from app.utils.web_helpers import _log_at_shutdown

    logger = logging.getLogger("g2.shutdown.level.test")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    stream = io.StringIO()
    logger.addHandler(logging.StreamHandler(stream))
    records: list[logging.LogRecord] = []
    logger.addHandler(type("Collect", (logging.Handler,), {"emit": lambda self, r: records.append(r)})())
    try:
        _log_at_shutdown(logger, "stuck thread", logging.WARNING)
        assert [r.levelno for r in records] == [logging.WARNING]
        assert "stuck thread" in stream.getvalue()

        stream.close()  # the atexit case: nothing is logged, no traceback on stderr
        _log_at_shutdown(logger, "too late", logging.WARNING)
        assert [r.levelno for r in records] == [logging.WARNING]
        assert "Logging error" not in capsys.readouterr().err
    finally:
        logger.handlers.clear()


def test_security_hook_keeps_sessions_permanent_without_touching_app_config(web_app):
    with web_app.test_request_context("/token", base_url="https://ddc.example"):
        web_app.preprocess_request()
        assert session.permanent is True
    assert web_app.config["SESSION_COOKIE_SECURE"] is False
