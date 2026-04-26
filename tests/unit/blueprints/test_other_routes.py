# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Blueprint Functional Tests                     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Functional tests for the four small blueprints.

Targets
-------
- ``app/blueprints/translation_routes.py``  (channel-pair API + provider test)
- ``app/blueprints/log_routes.py``           (log fetch endpoints)
- ``app/blueprints/tasks_bp.py``             (task management endpoints)
- ``app/blueprints/action_log_routes.py``    (action-log fetch / clear / dl)

Strategy
--------
Each blueprint is mounted on a *minimal* Flask application built inside its
fixture so we never load the full ``create_app`` stack (which would drag in
Docker / scheduler / mech services).  HTTP basic auth is stubbed via
``auth.verify_password`` so all ``@auth.login_required`` routes accept the
fake credentials.  Service singletons are replaced with ``Mock`` objects via
``monkeypatch`` on the relevant ``get_xxx_service`` factory.

The SSRF whitelist itself is already covered in
``tests/unit/security/test_bundle3_security.py`` — these tests only exercise
the *handler* paths (input validation, provider dispatch, error mapping).
"""

from __future__ import annotations

import base64
import io
import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Auth header used for every request — verify_password is stubbed to accept it
# ---------------------------------------------------------------------------

_AUTH_HEADER = {
    "Authorization": "Basic " + base64.b64encode(b"admin:test").decode(),
}


def _build_app(register, monkeypatch):
    """Build a minimal Flask app with auth stubbed.

    ``register(app)`` registers the blueprint(s) under test on ``app``.
    """
    # Stub out the ``verify_password`` callback so any Authorization: Basic
    # header is accepted.  We patch on the shared ``auth`` instance.
    from app import auth as auth_module

    monkeypatch.setattr(
        auth_module.auth, "verify_password_callback", lambda u, p: "admin"
    )

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-blueprint-routes"
    app.config["WTF_CSRF_ENABLED"] = False
    register(app)
    return app


# ===========================================================================
# Translation routes
# ===========================================================================


@pytest.fixture
def translation_app(monkeypatch):
    from app.blueprints.translation_routes import translation_bp

    return _build_app(lambda app: app.register_blueprint(translation_bp), monkeypatch)


@pytest.fixture
def mock_translation_config(monkeypatch):
    """Replace ``get_translation_config_service`` with a fresh MagicMock."""
    svc = MagicMock()
    monkeypatch.setattr(
        "app.blueprints.translation_routes.get_translation_config_service",
        lambda: svc,
    )
    return svc


@pytest.fixture
def mock_translation_service(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(
        "app.blueprints.translation_routes.get_translation_service",
        lambda: svc,
    )
    return svc


class TestTranslationPairs:
    """GET/POST/PUT/DELETE on /api/translation/pairs."""

    def test_get_pairs_returns_serialized_pairs(
        self, translation_app, mock_translation_config
    ):
        pair = MagicMock()
        pair.to_dict.return_value = {"id": "p1", "name": "alpha", "enabled": True}
        mock_translation_config.get_pairs.return_value = [pair]

        client = translation_app.test_client()
        resp = client.get("/api/translation/pairs", headers=_AUTH_HEADER)

        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {"pairs": [{"id": "p1", "name": "alpha", "enabled": True}]}

    def test_get_pairs_returns_500_on_service_exception(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.get_pairs.side_effect = RuntimeError("boom")

        client = translation_app.test_client()
        resp = client.get("/api/translation/pairs", headers=_AUTH_HEADER)

        assert resp.status_code == 500
        body = resp.get_json()
        assert body["pairs"] == []
        assert body["error"]

    def test_create_pair_requires_body(
        self, translation_app, mock_translation_config
    ):
        client = translation_app.test_client()
        # An empty JSON body — request.json evaluates to None, so the handler
        # returns the 'Request body is required' 400. The exact response body
        # depends on whether Flask's get_json silently returns None or raises;
        # either way the status must be 400 and the service must NOT be hit.
        resp = client.post(
            "/api/translation/pairs",
            data="",
            content_type="application/json",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        mock_translation_config.add_pair.assert_not_called()

    def test_create_pair_success(
        self, translation_app, mock_translation_config
    ):
        result = MagicMock()
        result.success = True
        result.data.to_dict.return_value = {"id": "new", "name": "fresh"}
        mock_translation_config.add_pair.return_value = result

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/pairs",
            json={"name": "fresh", "source_channel_id": "1", "target_channel_id": "2"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["success"] is True
        assert body["pair"]["id"] == "new"

    def test_create_pair_validation_error(
        self, translation_app, mock_translation_config
    ):
        result = MagicMock()
        result.success = False
        result.error = "Invalid channel id"
        mock_translation_config.add_pair.return_value = result

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/pairs",
            json={"name": "broken"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Invalid channel id"

    def test_update_pair_404_when_missing(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.get_pair.return_value = None

        client = translation_app.test_client()
        resp = client.put(
            "/api/translation/pairs/abc",
            json={"name": "x"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 404

    def test_update_pair_success(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.get_pair.return_value = MagicMock()
        ok = MagicMock(success=True)
        mock_translation_config.update_pair.return_value = ok

        client = translation_app.test_client()
        resp = client.put(
            "/api/translation/pairs/abc",
            json={"name": "x"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_update_pair_requires_body(
        self, translation_app, mock_translation_config
    ):
        client = translation_app.test_client()
        # Force empty JSON body
        resp = client.put(
            "/api/translation/pairs/abc",
            data="",
            content_type="application/json",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_delete_pair_404_when_missing(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.get_pair.return_value = None

        client = translation_app.test_client()
        resp = client.delete(
            "/api/translation/pairs/abc", headers=_AUTH_HEADER
        )
        assert resp.status_code == 404

    def test_delete_pair_success(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.get_pair.return_value = MagicMock()
        mock_translation_config.delete_pair.return_value = MagicMock(success=True)

        client = translation_app.test_client()
        resp = client.delete(
            "/api/translation/pairs/abc", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_toggle_pair_resets_auto_disabled_on_success(
        self, translation_app, mock_translation_config, mock_translation_service
    ):
        mock_translation_config.get_pair.return_value = MagicMock()
        mock_translation_config.toggle_pair.return_value = MagicMock(
            success=True, data={"enabled": True}
        )

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/pairs/abc/toggle", headers=_AUTH_HEADER
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True and body["enabled"] is True
        mock_translation_service.reset_auto_disabled.assert_called_once_with("abc")

    def test_toggle_pair_404_when_missing(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.get_pair.return_value = None

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/pairs/missing/toggle", headers=_AUTH_HEADER
        )
        assert resp.status_code == 404


class TestTranslationSettings:
    def test_get_settings_redacts_api_key(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "TRANSLATION_API_KEY"
        settings.api_key_encrypted = "gAAAAAencrypted"
        settings.to_dict.return_value = {
            "provider": "deepl",
            "api_key_encrypted": "gAAAAAencrypted",
            "api_key_env": "TRANSLATION_API_KEY",
        }
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.delenv("TRANSLATION_API_KEY", raising=False)

        client = translation_app.test_client()
        resp = client.get("/api/translation/settings", headers=_AUTH_HEADER)

        assert resp.status_code == 200
        body = resp.get_json()["settings"]
        # The actual encrypted value must NOT leak
        assert "api_key_encrypted" not in body
        # Source should be 'config' since env unset but encrypted set
        assert body["api_key_configured"] is True
        assert body["api_key_source"] == "config"

    def test_get_settings_reports_env_source(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "TEST_KEY_ENV"
        settings.api_key_encrypted = None
        settings.to_dict.return_value = {"provider": "deepl"}
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("TEST_KEY_ENV", "real-key")

        client = translation_app.test_client()
        resp = client.get("/api/translation/settings", headers=_AUTH_HEADER)
        body = resp.get_json()["settings"]
        assert body["api_key_source"] == "env"
        assert body["api_key_configured"] is True

    def test_get_settings_reports_none_source(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "TEST_KEY_ENV"
        settings.api_key_encrypted = None
        settings.to_dict.return_value = {"provider": "deepl"}
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.delenv("TEST_KEY_ENV", raising=False)

        client = translation_app.test_client()
        resp = client.get("/api/translation/settings", headers=_AUTH_HEADER)
        body = resp.get_json()["settings"]
        assert body["api_key_source"] == "none"
        assert body["api_key_configured"] is False

    def test_update_settings_requires_body(
        self, translation_app, mock_translation_config
    ):
        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/settings",
            data="",
            content_type="application/json",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_update_settings_passes_through(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.update_settings.return_value = MagicMock(success=True)

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/settings",
            json={"provider": "google"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        mock_translation_config.update_settings.assert_called_once_with(
            {"provider": "google"}
        )

    def test_save_api_key_clears_when_empty(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.save_api_key.return_value = MagicMock(success=True)

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/apikey",
            json={"api_key": "   "},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        mock_translation_config.save_api_key.assert_called_once_with(None)

    def test_save_api_key_stores_when_provided(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.save_api_key.return_value = MagicMock(success=True)

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/apikey",
            json={"api_key": "secret-key"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        mock_translation_config.save_api_key.assert_called_once_with("secret-key")

    def test_save_api_key_handles_exception(
        self, translation_app, mock_translation_config
    ):
        mock_translation_config.save_api_key.side_effect = RuntimeError("fs error")

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/apikey",
            json={"api_key": "x"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False


class TestTranslationTest:
    """POST /api/translation/test handler — focus on input + dispatch logic.

    The SSRF allow-list itself is already covered in Bundle 3 tests; we only
    check that handler-level branches behave correctly.
    """

    def test_test_requires_body(self, translation_app, mock_translation_config):
        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/test",
            data="",
            content_type="application/json",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_test_requires_text(self, translation_app, mock_translation_config):
        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/test",
            json={"text": "   "},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "text is required" in resp.get_json()["error"].lower()

    def test_test_rejects_too_long_text(
        self, translation_app, mock_translation_config
    ):
        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/test",
            json={"text": "a" * 1001},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "too long" in resp.get_json()["error"].lower()

    def test_test_returns_400_when_no_api_key(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "MISSING_KEY"
        settings.api_key_encrypted = None
        settings.provider = "deepl"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.delenv("MISSING_KEY", raising=False)

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/test",
            json={"text": "hello", "target_language": "DE"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "no api key" in resp.get_json()["error"].lower()

    def test_test_unknown_provider_returns_400(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "FOO_KEY"
        settings.api_key_encrypted = None
        settings.provider = "bogus"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("FOO_KEY", "k")

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/test",
            json={"text": "hello"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "unknown provider" in resp.get_json()["error"].lower()


class TestTranslationLanguages:
    def test_get_languages_returns_supported(self, translation_app):
        client = translation_app.test_client()
        resp = client.get("/api/translation/languages", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "languages" in data
        assert isinstance(data["languages"], dict)


class TestTranslationProviderDispatch:
    """Cover the per-provider success paths of POST /api/translation/test.

    We replace ``urllib.request.urlopen`` (used inside the route's nested
    helper) with a fake that returns a configured payload. The SSRF allow-list
    is preserved — we use real provider URLs that are on the whitelist.
    """

    def _make_urlopen(self, status, json_payload):
        from contextlib import contextmanager

        @contextmanager
        def fake_urlopen(req, timeout=None, context=None):
            class _Resp:
                def __init__(self_inner, status_, payload):
                    self_inner.status = status_
                    self_inner._b = json.dumps(payload).encode("utf-8")

                def read(self_inner):
                    return self_inner._b

            yield _Resp(status, json_payload)

        return fake_urlopen

    def test_deepl_provider_success(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "DEEPL_KEY"
        settings.api_key_encrypted = None
        settings.provider = "deepl"
        settings.deepl_api_url = "https://api-free.deepl.com/v2/translate"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("DEEPL_KEY", "k")

        fake = self._make_urlopen(
            200,
            {"translations": [{"text": "Hallo", "detected_source_language": "EN"}]},
        )
        with patch("urllib.request.urlopen", fake):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello", "target_language": "DE"},
                headers=_AUTH_HEADER,
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["success"] is True
        assert body["translated_text"] == "Hallo"
        assert body["provider"] == "DeepL"
        assert body["detected_language"] == "EN"

    def test_deepl_provider_with_source_language(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "DEEPL_KEY"
        settings.api_key_encrypted = None
        settings.provider = "deepl"
        settings.deepl_api_url = "https://api-free.deepl.com/v2/translate"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("DEEPL_KEY", "k")

        fake = self._make_urlopen(200, {"translations": [{"text": "Hallo"}]})
        with patch("urllib.request.urlopen", fake):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello", "target_language": "DE", "source_language": "EN"},
                headers=_AUTH_HEADER,
            )
        assert resp.status_code == 200

    def test_deepl_provider_http_error(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "DEEPL_KEY"
        settings.api_key_encrypted = None
        settings.provider = "deepl"
        settings.deepl_api_url = "https://api-free.deepl.com/v2/translate"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("DEEPL_KEY", "k")

        # Non-200 response triggers the "DeepL API error" branch.
        fake = self._make_urlopen(403, {})
        with patch("urllib.request.urlopen", fake):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello"},
                headers=_AUTH_HEADER,
            )
        assert resp.status_code == 400
        body = resp.get_json()
        assert "DeepL" in body["error"]

    def test_google_provider_success(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "GKEY"
        settings.api_key_encrypted = None
        settings.provider = "google"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("GKEY", "k")

        fake = self._make_urlopen(
            200,
            {
                "data": {
                    "translations": [
                        {"translatedText": "Bonjour", "detectedSourceLanguage": "en"}
                    ]
                }
            },
        )
        with patch("urllib.request.urlopen", fake):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello", "target_language": "FR", "source_language": "EN"},
                headers=_AUTH_HEADER,
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["provider"] == "Google"
        assert body["translated_text"] == "Bonjour"

    def test_google_provider_http_error(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "GKEY"
        settings.api_key_encrypted = None
        settings.provider = "google"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("GKEY", "k")

        fake = self._make_urlopen(500, {})
        with patch("urllib.request.urlopen", fake):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello"},
                headers=_AUTH_HEADER,
            )
        assert resp.status_code == 400
        assert "Google" in resp.get_json()["error"]

    def test_microsoft_provider_success(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "MSKEY"
        settings.api_key_encrypted = None
        settings.provider = "microsoft"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("MSKEY", "k")

        fake = self._make_urlopen(
            200,
            [
                {
                    "translations": [{"text": "Bonjour"}],
                    "detectedLanguage": {"language": "en"},
                }
            ],
        )
        with patch("urllib.request.urlopen", fake):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello", "target_language": "FR", "source_language": "EN"},
                headers=_AUTH_HEADER,
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["provider"] == "Microsoft"
        assert body["translated_text"] == "Bonjour"
        assert body["detected_language"] == "en"

    def test_microsoft_provider_http_error(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        settings = MagicMock()
        settings.api_key_env = "MSKEY"
        settings.api_key_encrypted = None
        settings.provider = "microsoft"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("MSKEY", "k")

        fake = self._make_urlopen(401, [])
        with patch("urllib.request.urlopen", fake):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello"},
                headers=_AUTH_HEADER,
            )
        assert resp.status_code == 400

    def test_translation_test_handles_url_error(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        """URLError raised by urlopen should map to the 400 'API error' branch."""
        import urllib.error

        settings = MagicMock()
        settings.api_key_env = "DEEPL_KEY"
        settings.api_key_encrypted = None
        settings.provider = "deepl"
        settings.deepl_api_url = "https://api-free.deepl.com/v2/translate"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("DEEPL_KEY", "k")

        def boom(*a, **kw):
            raise urllib.error.URLError("connection reset")

        with patch("urllib.request.urlopen", boom):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello"},
                headers=_AUTH_HEADER,
            )
        assert resp.status_code == 400
        assert "API error" in resp.get_json()["error"]

    def test_translation_test_handles_unexpected_exception(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        """Generic exception inside the dispatch falls into the 500 branch."""
        settings = MagicMock()
        settings.api_key_env = "DEEPL_KEY"
        settings.api_key_encrypted = None
        settings.provider = "deepl"
        settings.deepl_api_url = "https://api-free.deepl.com/v2/translate"
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.setenv("DEEPL_KEY", "k")

        def boom(*a, **kw):
            raise RuntimeError("blow up")

        with patch("urllib.request.urlopen", boom):
            client = translation_app.test_client()
            resp = client.post(
                "/api/translation/test",
                json={"text": "Hello"},
                headers=_AUTH_HEADER,
            )
        assert resp.status_code == 500
        assert "failed" in resp.get_json()["error"].lower()

    def test_translation_settings_handles_exception(
        self, translation_app, mock_translation_config
    ):
        """get_settings exception → 500."""
        mock_translation_config.get_settings.side_effect = RuntimeError("nope")

        client = translation_app.test_client()
        resp = client.get("/api/translation/settings", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["settings"] == {}
        assert body["error"]

    def test_translation_decrypts_legacy_plain_api_key(
        self, translation_app, mock_translation_config, monkeypatch
    ):
        """Pre-encryption plain-text key in api_key_encrypted is used directly."""
        settings = MagicMock()
        settings.api_key_env = "MISSING_KEY"
        # No 'gAAAAA' prefix → handler treats it as plain-text, not encrypted.
        settings.api_key_encrypted = "plain-legacy-key"
        settings.provider = "bogus"  # short-circuits to the unknown-provider 400
        mock_translation_config.get_settings.return_value = settings
        monkeypatch.delenv("MISSING_KEY", raising=False)

        client = translation_app.test_client()
        resp = client.post(
            "/api/translation/test",
            json={"text": "hi"},
            headers=_AUTH_HEADER,
        )
        # Provider bogus → unknown-provider 400 (NOT "no api key configured"),
        # which proves the legacy plain key was accepted.
        assert resp.status_code == 400
        assert "unknown provider" in resp.get_json()["error"].lower()


# ===========================================================================
# Log routes
# ===========================================================================


@pytest.fixture
def log_app(monkeypatch):
    from app.blueprints.log_routes import log_bp

    return _build_app(lambda app: app.register_blueprint(log_bp), monkeypatch)


@pytest.fixture
def mock_log_service(monkeypatch):
    """Replace ``get_container_log_service`` with a MagicMock for every call."""
    svc = MagicMock()
    monkeypatch.setattr(
        "services.web.container_log_service.get_container_log_service",
        lambda: svc,
    )
    return svc


def _ok(content=None, data=None, status=200):
    """Build a successful LogResult-shaped Mock."""
    r = MagicMock()
    r.success = True
    r.content = content
    r.data = data
    r.status_code = status
    r.error = None
    return r


def _fail(error="bad", status=500):
    r = MagicMock()
    r.success = False
    r.content = None
    r.data = None
    r.error = error
    r.status_code = status
    return r


class TestLogRoutes:
    def test_container_logs_success(self, log_app, mock_log_service):
        mock_log_service.get_container_logs.return_value = _ok(content="ok logs")

        client = log_app.test_client()
        resp = client.get("/container_logs/myname", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.mimetype == "text/plain"
        assert resp.data == b"ok logs"

    def test_container_logs_failure_uses_status(self, log_app, mock_log_service):
        mock_log_service.get_container_logs.return_value = _fail(
            "missing", status=404
        )

        client = log_app.test_client()
        resp = client.get("/container_logs/myname", headers=_AUTH_HEADER)
        assert resp.status_code == 404
        assert b"Failed to fetch container logs" in resp.data

    def test_bot_logs_success(self, log_app, mock_log_service):
        mock_log_service.get_filtered_logs.return_value = _ok(content="bot lines")

        client = log_app.test_client()
        resp = client.get("/bot_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.data == b"bot lines"

    def test_discord_logs_success(self, log_app, mock_log_service):
        mock_log_service.get_filtered_logs.return_value = _ok(content="discord lines")

        client = log_app.test_client()
        resp = client.get("/discord_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.data == b"discord lines"

    def test_webui_logs_success(self, log_app, mock_log_service):
        mock_log_service.get_filtered_logs.return_value = _ok(content="webui lines")

        client = log_app.test_client()
        resp = client.get("/webui_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.data == b"webui lines"

    def test_application_logs_failure(self, log_app, mock_log_service):
        mock_log_service.get_filtered_logs.return_value = _fail(
            "no permission", status=500
        )

        client = log_app.test_client()
        resp = client.get("/application_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_action_logs_text(self, log_app, mock_log_service):
        mock_log_service.get_action_logs.return_value = _ok(content="2025 acted")

        client = log_app.test_client()
        resp = client.get("/action_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.data == b"2025 acted"

    def test_action_logs_json_returns_data(self, log_app, mock_log_service):
        payload = {"entries": [{"action": "START", "container": "x"}]}
        mock_log_service.get_action_logs.return_value = _ok(data=payload)

        client = log_app.test_client()
        resp = client.get("/action_logs_json", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.get_json() == payload

    def test_action_logs_json_failure_returns_error(
        self, log_app, mock_log_service
    ):
        mock_log_service.get_action_logs.return_value = _fail("oops", status=500)

        client = log_app.test_client()
        resp = client.get("/action_logs_json", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["success"] is False
        assert "error" in body

    def test_clear_logs_success_passes_log_type(self, log_app, mock_log_service):
        mock_log_service.clear_logs.return_value = _ok(data={"success": True, "cleared": 3})

        client = log_app.test_client()
        resp = client.post(
            "/clear_logs",
            json={"log_type": "bot"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        # The service should have been called with a ClearLogRequest carrying our log_type.
        called_arg = mock_log_service.clear_logs.call_args[0][0]
        assert called_arg.log_type == "bot"

    def test_clear_logs_defaults_to_container_when_no_body(
        self, log_app, mock_log_service
    ):
        mock_log_service.clear_logs.return_value = _ok(data={"success": True})

        client = log_app.test_client()
        # Empty JSON object — `request.json` returns {} (falsy → default branch).
        resp = client.post(
            "/clear_logs",
            json={},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        called_arg = mock_log_service.clear_logs.call_args[0][0]
        assert called_arg.log_type == "container"

    def test_clear_logs_failure_returns_status(self, log_app, mock_log_service):
        mock_log_service.clear_logs.return_value = _fail("nope", status=500)

        client = log_app.test_client()
        resp = client.post(
            "/clear_logs",
            json={"log_type": "bot"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_log_route_handles_service_import_error(
        self, log_app, monkeypatch
    ):
        """When the service factory raises RuntimeError, route returns 500."""
        def boom():
            raise RuntimeError("service down")

        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service", boom
        )
        client = log_app.test_client()
        resp = client.get("/bot_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_container_logs_handles_value_error(
        self, log_app, monkeypatch
    ):
        """ValueError in service path triggers the data-error 500 branch."""
        svc = MagicMock()
        svc.get_container_logs.side_effect = ValueError("bad name")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        client = log_app.test_client()
        resp = client.get("/container_logs/x", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_discord_logs_handles_failure(self, log_app, mock_log_service):
        mock_log_service.get_filtered_logs.return_value = _fail("err", status=500)
        client = log_app.test_client()
        resp = client.get("/discord_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_webui_logs_handles_failure(self, log_app, mock_log_service):
        mock_log_service.get_filtered_logs.return_value = _fail("err", status=500)
        client = log_app.test_client()
        resp = client.get("/webui_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_action_logs_handles_failure(self, log_app, mock_log_service):
        mock_log_service.get_action_logs.return_value = _fail("err", status=500)
        client = log_app.test_client()
        resp = client.get("/action_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_bot_logs_handles_value_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_filtered_logs.side_effect = ValueError("bad")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        client = log_app.test_client()
        resp = client.get("/bot_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_action_logs_handles_value_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_action_logs.side_effect = ValueError("bad")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        client = log_app.test_client()
        resp = client.get("/action_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_action_logs_json_handles_runtime_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.get_action_logs.side_effect = RuntimeError("boom")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        client = log_app.test_client()
        resp = client.get("/action_logs_json", headers=_AUTH_HEADER)
        assert resp.status_code == 500
        assert resp.get_json()["success"] is False

    def test_clear_logs_handles_runtime_error(self, log_app, monkeypatch):
        svc = MagicMock()
        svc.clear_logs.side_effect = RuntimeError("nope")
        monkeypatch.setattr(
            "services.web.container_log_service.get_container_log_service",
            lambda: svc,
        )
        client = log_app.test_client()
        resp = client.post(
            "/clear_logs",
            json={"log_type": "container"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500

    def test_application_logs_success(self, log_app, mock_log_service):
        mock_log_service.get_filtered_logs.return_value = _ok(content="app logs")
        client = log_app.test_client()
        resp = client.get("/application_logs", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.data == b"app logs"


# ===========================================================================
# Tasks blueprint
# ===========================================================================


@pytest.fixture
def tasks_app(monkeypatch):
    from app.blueprints.tasks_bp import tasks_bp

    return _build_app(lambda app: app.register_blueprint(tasks_bp), monkeypatch)


@pytest.fixture
def mock_task_service(monkeypatch):
    svc = MagicMock()
    monkeypatch.setattr(
        "services.web.task_management_service.get_task_management_service",
        lambda: svc,
    )
    return svc


class TestTasksBlueprint:
    def test_add_task_requires_data(self, tasks_app, mock_task_service):
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/add",
            data="",
            content_type="application/json",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_add_task_requires_cycle(self, tasks_app, mock_task_service):
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/add",
            json={"container": "c", "action": "start"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "Cycle" in resp.get_json()["error"]

    def test_add_task_requires_container(self, tasks_app, mock_task_service):
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/add",
            json={"cycle": "daily", "action": "start"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "Container" in resp.get_json()["error"]

    def test_add_task_requires_action(self, tasks_app, mock_task_service):
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/add",
            json={"cycle": "daily", "container": "c"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "Action" in resp.get_json()["error"]

    def test_add_task_success(self, tasks_app, mock_task_service):
        mock_task_service.add_task.return_value = MagicMock(
            success=True,
            message="Task created",
            task_data={"id": "t1", "container": "c"},
        )

        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/add",
            json={
                "cycle": "daily",
                "container": "c",
                "action": "start",
                "schedule_details": {"hour": 8},
            },
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["task"]["id"] == "t1"

    def test_add_task_service_failure_returns_400(
        self, tasks_app, mock_task_service
    ):
        mock_task_service.add_task.return_value = MagicMock(
            success=False, error="invalid container", message=None, task_data=None
        )

        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/add",
            json={"cycle": "daily", "container": "c", "action": "start"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_list_tasks_success(self, tasks_app, mock_task_service):
        mock_task_service.list_tasks.return_value = MagicMock(
            success=True,
            tasks=[{"id": "t1"}, {"id": "t2"}],
            error=None,
        )

        client = tasks_app.test_client()
        resp = client.get("/tasks/list", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.get_json() == [{"id": "t1"}, {"id": "t2"}]

    def test_list_tasks_failure(self, tasks_app, mock_task_service):
        mock_task_service.list_tasks.return_value = MagicMock(
            success=False, tasks=None, error="db gone"
        )

        client = tasks_app.test_client()
        resp = client.get("/tasks/list", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_update_status_requires_json(self, tasks_app, mock_task_service):
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/update_status",
            data="not json",
            content_type="text/plain",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_update_status_requires_task_id(self, tasks_app, mock_task_service):
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/update_status",
            json={"is_active": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "task_id" in resp.get_json()["error"]

    def test_update_status_requires_is_active(
        self, tasks_app, mock_task_service
    ):
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/update_status",
            json={"task_id": "abc"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400
        assert "is_active" in resp.get_json()["error"]

    def test_update_status_success(self, tasks_app, mock_task_service):
        mock_task_service.update_task_status.return_value = MagicMock(
            success=True,
            message="ok",
            task_data={"id": "abc", "is_active": True},
        )

        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/update_status",
            json={"task_id": "abc", "is_active": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_update_status_not_found(self, tasks_app, mock_task_service):
        mock_task_service.update_task_status.return_value = MagicMock(
            success=False, error="Task not found", message=None, task_data=None
        )

        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/update_status",
            json={"task_id": "missing", "is_active": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 404

    def test_delete_task_success(self, tasks_app, mock_task_service):
        mock_task_service.delete_task.return_value = MagicMock(
            success=True, message="deleted", error=None
        )

        client = tasks_app.test_client()
        resp = client.delete("/tasks/delete/abc", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_delete_task_not_found(self, tasks_app, mock_task_service):
        mock_task_service.delete_task.return_value = MagicMock(
            success=False, error="Task not found", message=None
        )

        client = tasks_app.test_client()
        resp = client.delete("/tasks/delete/missing", headers=_AUTH_HEADER)
        assert resp.status_code == 404

    def test_delete_task_other_failure(self, tasks_app, mock_task_service):
        mock_task_service.delete_task.return_value = MagicMock(
            success=False, error="storage error", message=None
        )

        client = tasks_app.test_client()
        resp = client.delete("/tasks/delete/abc", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_edit_task_get_success(self, tasks_app, mock_task_service):
        mock_task_service.edit_task.return_value = MagicMock(
            success=True, task_data={"id": "abc"}, message=None, error=None
        )

        client = tasks_app.test_client()
        resp = client.get("/tasks/edit/abc", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.get_json()["task"]["id"] == "abc"

    def test_edit_task_get_not_found(self, tasks_app, mock_task_service):
        mock_task_service.edit_task.return_value = MagicMock(
            success=False, error="Task not found", task_data=None, message=None
        )

        client = tasks_app.test_client()
        resp = client.get("/tasks/edit/missing", headers=_AUTH_HEADER)
        assert resp.status_code == 404

    def test_edit_task_put_requires_data(self, tasks_app, mock_task_service):
        client = tasks_app.test_client()
        resp = client.put(
            "/tasks/edit/abc",
            data="",
            content_type="application/json",
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_edit_task_put_success(self, tasks_app, mock_task_service):
        mock_task_service.edit_task.return_value = MagicMock(
            success=True,
            task_data={"id": "abc", "container": "c"},
            message="updated",
            error=None,
        )

        client = tasks_app.test_client()
        resp = client.put(
            "/tasks/edit/abc",
            json={"container": "c", "cycle": "daily"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_edit_task_put_failure(self, tasks_app, mock_task_service):
        mock_task_service.edit_task.return_value = MagicMock(
            success=False, error="invalid", task_data=None, message=None
        )
        client = tasks_app.test_client()
        resp = client.put(
            "/tasks/edit/abc",
            json={"container": "c"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400

    def test_add_task_handles_runtime_error(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.add_task.side_effect = RuntimeError("svc down")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/add",
            json={"cycle": "daily", "container": "c", "action": "start"},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500

    def test_list_tasks_handles_runtime_error(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.list_tasks.side_effect = RuntimeError("svc down")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        client = tasks_app.test_client()
        resp = client.get("/tasks/list", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_delete_task_handles_runtime_error(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.delete_task.side_effect = RuntimeError("svc down")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        client = tasks_app.test_client()
        resp = client.delete("/tasks/delete/abc", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_edit_task_handles_runtime_error(self, tasks_app, monkeypatch):
        svc = MagicMock()
        svc.edit_task.side_effect = RuntimeError("svc down")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        client = tasks_app.test_client()
        resp = client.get("/tasks/edit/abc", headers=_AUTH_HEADER)
        assert resp.status_code == 500

    def test_update_status_handles_runtime_error(
        self, tasks_app, monkeypatch
    ):
        svc = MagicMock()
        svc.update_task_status.side_effect = RuntimeError("svc down")
        monkeypatch.setattr(
            "services.web.task_management_service.get_task_management_service",
            lambda: svc,
        )
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/update_status",
            json={"task_id": "abc", "is_active": False},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 500

    def test_update_status_other_failure_returns_400(
        self, tasks_app, mock_task_service
    ):
        mock_task_service.update_task_status.return_value = MagicMock(
            success=False, error="state conflict", task_data=None, message=None
        )
        client = tasks_app.test_client()
        resp = client.post(
            "/tasks/update_status",
            json={"task_id": "abc", "is_active": True},
            headers=_AUTH_HEADER,
        )
        assert resp.status_code == 400


# ===========================================================================
# Action log routes
# ===========================================================================


@pytest.fixture
def action_log_app(tmp_path, monkeypatch):
    """Build a Flask app with action_log_bp registered.

    The module reads ``ACTION_LOG_FILE`` at import time; we monkeypatch the
    *module-level* binding **and** the underlying constant so the route picks
    up our temp file.
    """
    log_file = tmp_path / "action_log.json"
    log_file.write_text("entry1\nentry2\n", encoding="utf-8")

    # Patch the symbol the route reads from
    monkeypatch.setattr(
        "app.blueprints.action_log_routes.ACTION_LOG_FILE", str(log_file)
    )

    # Stub log_user_action to avoid real-file side effects on /clear-action-log
    monkeypatch.setattr(
        "app.blueprints.action_log_routes.log_user_action",
        lambda *a, **kw: None,
    )

    # The /action-log route is wrapped by a 60-second per-IP rate limiter that
    # keeps state in a module-level dict. Reset it before every test so the
    # multiple GET cases below all see a fresh bucket.
    import app.blueprints.action_log_routes as _alr_mod

    if hasattr(_alr_mod, "_last_log_request"):
        _alr_mod._last_log_request.clear()

    from app.blueprints.action_log_routes import action_log_bp

    def register(app):
        # Provide a target endpoint so url_for('main_bp.config_page') resolves
        app.register_blueprint(action_log_bp)

        from flask import Blueprint as _B

        main_bp = _B("main_bp", __name__)

        @main_bp.route("/")
        def config_page():  # noqa: ANN001
            return "ok"

        app.register_blueprint(main_bp)

    app = _build_app(register, monkeypatch)
    app.config["log_path"] = str(log_file)
    return app


class TestActionLogRoutes:
    def test_get_action_log_returns_file_content(self, action_log_app):
        client = action_log_app.test_client()
        resp = client.get("/action-log", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert resp.mimetype == "text/plain"
        assert b"entry1" in resp.data
        assert b"entry2" in resp.data

    def test_get_action_log_handles_missing_file(
        self, action_log_app, monkeypatch
    ):
        monkeypatch.setattr(
            "app.blueprints.action_log_routes.ACTION_LOG_FILE",
            "/tmp/this/does/not/exist.json",
        )

        client = action_log_app.test_client()
        resp = client.get("/action-log", headers=_AUTH_HEADER)
        # Endpoint always returns 200 with a friendly message — see route impl.
        assert resp.status_code == 200
        assert b"not found" in resp.data.lower()

    def test_get_action_log_handles_io_error(
        self, action_log_app, monkeypatch
    ):
        # Force open() to raise an OSError
        real_open = open

        def raising_open(path, *a, **kw):
            if str(path).endswith("action_log.json"):
                raise OSError("disk on fire")
            return real_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", raising_open)

        client = action_log_app.test_client()
        resp = client.get("/action-log", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        assert b"Error reading action log" in resp.data

    def test_download_action_log_serves_file(self, action_log_app):
        client = action_log_app.test_client()
        resp = client.get("/download-action-log", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        # send_file will set a download disposition header.
        cd = resp.headers.get("Content-Disposition", "")
        assert "user_actions.log" in cd

    def test_download_action_log_redirects_when_missing(
        self, action_log_app, monkeypatch
    ):
        monkeypatch.setattr(
            "app.blueprints.action_log_routes.ACTION_LOG_FILE",
            "/tmp/missing-action-log.json",
        )
        client = action_log_app.test_client()
        resp = client.get(
            "/download-action-log",
            headers=_AUTH_HEADER,
            follow_redirects=False,
        )
        # send_file raises FileNotFoundError → handler redirects.
        # Some Flask versions raise NotFound (404); accept either contract.
        assert resp.status_code in {302, 404, 500}

    def test_clear_action_log_writes_marker_and_returns_json(
        self, action_log_app
    ):
        client = action_log_app.test_client()
        resp = client.post("/clear-action-log", headers=_AUTH_HEADER)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True

        # Verify the file was rewritten with the cleared marker
        path = action_log_app.config["log_path"]
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Log cleared by user" in content

    def test_clear_action_log_handles_io_error(
        self, action_log_app, monkeypatch
    ):
        real_open = open

        def raising_open(path, mode="r", *a, **kw):
            if str(path).endswith("action_log.json") and "w" in mode:
                raise PermissionError("denied")
            return real_open(path, mode, *a, **kw)

        monkeypatch.setattr("builtins.open", raising_open)

        client = action_log_app.test_client()
        resp = client.post("/clear-action-log", headers=_AUTH_HEADER)
        # Route swallows the error and returns JSON with success=False.
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is False
