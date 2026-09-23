# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package D2: CSRF enforcement, JS translations, config form, locales."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from flask import Blueprint, Flask, jsonify

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCALES_DIR = PROJECT_ROOT / "locales"
TEMPLATES_DIR = PROJECT_ROOT / "app" / "templates"
JS_DIR = PROJECT_ROOT / "app" / "static" / "js"

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_T_CALL_RE = re.compile(r"""(?<![\w$.])t\(\s*['"]([\w.-]+)['"]""")


def _frontend_sources():
    return sorted(TEMPLATES_DIR.rglob("*.html")) + sorted(JS_DIR.glob("*.js"))


def _load_locale(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _content_locales():
    return sorted(p for p in LOCALES_DIR.glob("*.json") if p.stem != "meta" and not p.stem.startswith("_"))


# ---------------------------------------------------------------------------
# D2-1: CSRF is enforced on blueprint routes
# ---------------------------------------------------------------------------


@pytest.fixture
def csrf_app():
    """Blueprint registered *before* install_csrf_protection, as in create_app()."""
    from flask_wtf.csrf import generate_csrf

    from app.web.csrf import install_csrf_protection

    app = Flask(__name__)
    app.config.update(SECRET_KEY="test-d2-csrf", TESTING=True)
    bp = Blueprint("d2_bp", __name__)

    @bp.route("/token")
    def token():
        return jsonify(token=generate_csrf())

    @bp.route("/save", methods=["POST"])
    def save():
        return jsonify(success=True)

    app.register_blueprint(bp)
    install_csrf_protection(app)
    return app


def _token(client) -> str:
    return client.get("/token").get_json()["token"]


def test_blueprint_post_without_token_is_rejected_as_json(csrf_app):
    resp = csrf_app.test_client().post("/save", json={}, headers={"Accept": "application/json"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["csrf_error"] is True
    assert "reload" in body["error"].lower()
    assert body["message"] == body["error"]


def test_blueprint_post_with_header_token_passes(csrf_app):
    client = csrf_app.test_client()
    token = _token(client)
    resp = client.post("/save", json={}, headers={"X-CSRFToken": token})
    assert resp.status_code == 200
    assert resp.get_json() == {"success": True}


def test_blueprint_post_with_form_field_token_passes(csrf_app):
    client = csrf_app.test_client()
    token = _token(client)
    resp = client.post("/save", data={"csrf_token": token})
    assert resp.status_code == 200


def test_token_without_matching_session_is_rejected(csrf_app):
    # A cross-site request never carries the (SameSite=Strict) session cookie.
    token = _token(csrf_app.test_client())
    resp = csrf_app.test_client().post("/save", data={"csrf_token": token})
    assert resp.status_code == 400


def test_native_form_post_without_token_gets_html_page(csrf_app):
    resp = csrf_app.test_client().post(
        "/save",
        data={"x": "1"},
        headers={"Sec-Fetch-Mode": "navigate", "Accept": "text/html,application/xhtml+xml"},
    )
    assert resp.status_code == 400
    assert resp.mimetype == "text/html"
    assert "Session expired" in resp.get_data(as_text=True)


@pytest.fixture
def factory_app(monkeypatch):
    """The real app factory (all blueprints), first-run state, no config writes."""
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    config_state = {"web_ui_password_hash": None}
    monkeypatch.setattr("app.blueprints.main_routes.load_config", lambda: config_state)
    monkeypatch.setattr("app.auth.load_config", lambda: config_state)

    def no_write(fields):
        raise AssertionError(f"setup must not save in this test: {fields}")

    monkeypatch.setattr("app.blueprints.main_routes.update_config_fields", no_write)
    monkeypatch.setattr("app.utils.shared_data.load_active_containers_from_config", lambda: [], raising=False)
    monkeypatch.setattr("app.utils.web_helpers.setup_action_logger", lambda app: None, raising=False)

    from app import auth as _auth

    _auth.setup_limiter.ip_dict.clear()
    _auth.auth_limiter.ip_dict.clear()

    from app.web import create_app

    return create_app({"TESTING": True})


def test_factory_setup_post_requires_token(factory_app):
    client = factory_app.test_client()
    resp = client.post(
        "/setup",
        data={"password": "Aa1!aaaaaaaaaa", "confirm_password": "different"},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["csrf_error"] is True


def test_factory_setup_page_token_is_accepted(factory_app):
    client = factory_app.test_client()
    page = client.get("/setup")
    assert page.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    assert match, "setup.html must embed the CSRF token in its form"

    resp = client.post(
        "/setup",
        data={"password": "Aa1!aaaaaaaaaa", "confirm_password": "different", "csrf_token": match.group(1)},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"success": False, "error": "Passwords do not match"}


def test_base_template_attaches_token_to_fetch_and_forms():
    base = (TEMPLATES_DIR / "_base.html").read_text(encoding="utf-8")
    assert '<meta name="csrf-token" content="{{ csrf_token() }}">' in base
    assert "window.fetch = function" in base
    assert "headers.set('X-CSRFToken', csrfToken)" in base
    assert "input.name = 'csrf_token'" in base


def test_every_page_with_post_form_or_fetch_can_send_a_token():
    """Full pages that post must extend _base.html or embed csrf_token() themselves."""
    offenders = []
    for path in TEMPLATES_DIR.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        if not text.lstrip().startswith(("<!doctype", "<!DOCTYPE", "<!--")) or "<html" not in text.lower():
            continue  # partials are included into a page
        posts = re.search(r"method\s*[:=]\s*['\"]?post", text, re.IGNORECASE)
        if posts and "extends '_base.html'" not in text and "csrf_token()" not in text:
            offenders.append(path.name)
    assert not offenders


# ---------------------------------------------------------------------------
# D2-2: t('web.…') resolves in JS
# ---------------------------------------------------------------------------


@pytest.fixture
def i18n_service():
    from services.web.i18n_service import I18nService

    return I18nService()


def _t_keys():
    keys = set()
    for path in _frontend_sources():
        keys.update(_T_CALL_RE.findall(path.read_text(encoding="utf-8")))
    return keys


def test_every_t_key_resolves_in_js_payload(i18n_service):
    js = i18n_service.get_js_translations("en")
    keys = _t_keys()
    assert any(k.startswith("web.") for k in keys)
    unresolved = sorted(k for k in keys if not js.get(k) or js[k] == k)
    assert not unresolved, f"t() keys without translation: {unresolved[:10]}"


def test_web_keys_keep_placeholders(i18n_service):
    js = i18n_service.get_js_translations("en")
    value = js["web.donations.confirm_delete_line1"]
    assert "{donor}" in value and "{amount}" in value


def test_web_keys_are_translated_for_ui_language(i18n_service):
    en = i18n_service.get_js_translations("en")
    de = i18n_service.get_js_translations("de")
    web_keys = [k for k in en if k.startswith("web.")]
    assert any(de[k] != en[k] for k in web_keys)


def test_only_referenced_web_keys_are_embedded(i18n_service):
    js = i18n_service.get_js_translations("en")
    embedded = {k for k in js if k.startswith("web.")}
    assert embedded == set(i18n_service.get_js_web_keys()) - {k for k in i18n_service.get_js_web_keys() if not js.get(k)}
    en_web = [k for k in _load_locale(LOCALES_DIR / "en.json") if k.startswith("web.")]
    assert len(embedded) < len(en_web) / 2


# ---------------------------------------------------------------------------
# D2-3: #config-form never submits natively
# ---------------------------------------------------------------------------


def test_config_form_submit_is_routed_to_ajax_save():
    # Its script moved to app/static on 2026-09-23; the markup stayed.
    scripts = (TEMPLATES_DIR.parent / "static" / "js" / "panel.js").read_text(encoding="utf-8")
    assert re.search(
        r"configForm\.addEventListener\('submit',\s*function\(event\)\s*\{\s*"
        r"event\.preventDefault\(\);\s*saveConfigAjax\(\);",
        scripts,
    )


def test_permissions_table_always_sends_channel_marker():
    # D1: an empty channel set is only saved when this marker arrives with the form.
    table = (TEMPLATES_DIR / "_permissions_table.html").read_text(encoding="utf-8")
    marker = '<input type="hidden" name="channel_tables_submitted" value="1">'
    assert marker in table
    assert table.index(marker) < table.index("{% for channel_id, channel_data in channel_permissions.items() %}")


def test_scheduler_interval_placeholder_matches_default():
    # Its script moved to app/static on 2026-09-23; the markup stayed.
    modal = ((TEMPLATES_DIR / "_advanced_settings_modal.html").read_text(encoding="utf-8")
             + (TEMPLATES_DIR.parent / "static" / "js" / "advanced_settings_modal.js").read_text(encoding="utf-8"))
    field = re.search(r'<input[^>]*name="env_DDC_SCHEDULER_CHECK_INTERVAL"[^>]*>', modal).group(0)
    assert 'placeholder="60"' in field


# ---------------------------------------------------------------------------
# D2-4 / D2-5: locale wording and completeness
# ---------------------------------------------------------------------------


def test_duplicate_channel_message_covers_same_table_duplicates():
    for code in ("en", "de"):
        value = _load_locale(LOCALES_DIR / f"{code}.json")["js.permissions.duplicate_channel_ids"]
        assert "{ids}" in value
    assert "used in both" not in _load_locale(LOCALES_DIR / "en.json")["js.permissions.duplicate_channel_ids"]


@pytest.mark.parametrize(
    "key, placeholder",
    [
        # cogs/admin_overview.py (Stop All / Restart All)
        ("\nSkipped (action not allowed): **{count}** containers", "{count}"),
        # cogs/status_info_integration.py (task scheduling button)
        ("No schedulable actions (start/stop/restart) are allowed for {container}.", "{container}"),
    ],
)
def test_bot_strings_are_translatable(key, placeholder):
    # The bot's _() looks the English source string up as the key.
    assert _load_locale(LOCALES_DIR / "en.json")[key] == key
    assert placeholder in _load_locale(LOCALES_DIR / "de.json")[key]


@pytest.mark.parametrize("locale_path", _content_locales(), ids=lambda p: p.name)
def test_locale_has_same_keys_and_placeholders_as_english(locale_path):
    en = _load_locale(LOCALES_DIR / "en.json")
    data = _load_locale(locale_path)
    assert set(data) == set(en), sorted(set(en) ^ set(data))[:10]
    bad = [
        k for k, v in data.items()
        if isinstance(v, str) and set(_PLACEHOLDER_RE.findall(v)) != set(_PLACEHOLDER_RE.findall(en[k]))
    ]
    assert not bad, bad[:10]
