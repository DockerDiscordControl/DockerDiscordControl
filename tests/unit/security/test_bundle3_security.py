# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Bundle 3 Security Feature Tests                #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Unit tests for Bundle 3 security features.

Covers:
- SSRF whitelist for translation provider URLs (app/blueprints/translation_routes.py)
- Setup password policy (length + complexity)  in app/blueprints/main_routes.py
- Session idle timeout configuration in app/web/security.py
- /logout endpoint behaviour (401 + WWW-Authenticate, session cleared)
- Setup rate limiter (SimpleRateLimiter from app/auth.py)
"""

from __future__ import annotations

import base64
import importlib
import time
from datetime import datetime, timedelta, timezone

import pytest

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_web_app(monkeypatch):
    """Build a Flask app with minimal blueprints for endpoint-level tests."""
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "false")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "false")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-bundle3")

    # Avoid touching real Docker / filesystem during create_app
    monkeypatch.setattr(
        "app.utils.shared_data.load_active_containers_from_config", lambda: []
    )
    monkeypatch.setattr(
        "app.utils.web_helpers.setup_action_logger", lambda app: None
    )

    # Only register the main blueprint so /setup, /logout exist without dragging
    # the whole service stack.
    def register_only_main_blueprint(app):
        from app.blueprints.main_routes import main_bp

        app.register_blueprint(main_bp)

    monkeypatch.setattr(
        "app.web.blueprints.register_blueprints", register_only_main_blueprint
    )
    monkeypatch.setattr("app.web.routes.register_routes", lambda app: None)

    from app.web import create_app

    # The setup_limiter is module-level (5 req/min per IP). Other security
    # tests in the same session exhaust it from 127.0.0.1 long before we
    # run, so reset its state for every isolated app.
    from app import auth as _auth

    _auth.setup_limiter.ip_dict.clear()
    _auth.auth_limiter.ip_dict.clear()

    return create_app({"TESTING": True})


# ---------------------------------------------------------------------------
# 1) SSRF whitelist for translation API
# ---------------------------------------------------------------------------


class TestTranslationSSRFWhitelist:
    """`_is_allowed_translation_url` must only let through HTTPS to known hosts."""

    def _checker(self):
        from app.blueprints.translation_routes import _is_allowed_translation_url

        return _is_allowed_translation_url

    def test_whitelisted_https_hosts_are_allowed(self):
        check = self._checker()
        for url in (
            "https://api.deepl.com/v2/translate",
            "https://api-free.deepl.com/v2/translate",
            "https://translation.googleapis.com/language/translate/v2",
            "https://api.cognitive.microsofttranslator.com/translate",
        ):
            assert check(url) is True, f"expected allowed for {url}"

    def test_http_scheme_is_rejected(self):
        check = self._checker()
        # Same hostname, but plaintext HTTP must be rejected.
        assert check("http://api.deepl.com/v2/translate") is False

    def test_localhost_and_internal_ips_are_rejected(self):
        check = self._checker()
        for url in (
            "https://localhost/v2/translate",
            "https://127.0.0.1/v2/translate",
            "https://169.254.169.254/latest/meta-data/",  # AWS metadata
            "https://10.0.0.5/internal",
            "https://192.168.1.1/admin",
            "https://[::1]/v2/translate",
        ):
            assert check(url) is False, f"expected rejected for {url}"

    def test_arbitrary_foreign_hosts_are_rejected(self):
        check = self._checker()
        for url in (
            "https://evil.example.com/v2/translate",
            "https://api.deepl.com.evil.tld/v2/translate",
            "https://google.com/translate",
        ):
            assert check(url) is False, f"expected rejected for {url}"

    def test_malformed_inputs_return_false_without_exception(self):
        check = self._checker()
        # None, empty string, garbage strings must all return False, never raise.
        for bad in (None, "", "not a url", "://", "ftp://", "javascript:alert(1)"):
            try:
                result = check(bad)
            except Exception as exc:  # pragma: no cover
                pytest.fail(f"_is_allowed_translation_url raised for {bad!r}: {exc}")
            assert result is False, f"expected False for {bad!r}, got {result!r}"

    def test_whitelist_constant_matches_spec(self):
        """Defensive: lock the actual whitelist set so accidental edits show up."""
        from app.blueprints.translation_routes import _ALLOWED_TRANSLATION_HOSTS

        assert _ALLOWED_TRANSLATION_HOSTS == {
            "api.deepl.com",
            "api-free.deepl.com",
            "translation.googleapis.com",
            "api.cognitive.microsofttranslator.com",
        }


# ---------------------------------------------------------------------------
# 2) Password policy on /setup
# ---------------------------------------------------------------------------


class TestSetupPasswordPolicy:
    """POST /setup must enforce length >= 12 and complexity >= 3 of 4 classes."""

    def _post_setup(self, isolated_web_app, monkeypatch, password, *, configured=False):
        """Run a POST against /setup with the given password.

        ``configured=False`` simulates first-time setup (no password hash);
        ``configured=True`` simulates a pre-configured installation.
        """
        config_state = {
            "web_ui_password_hash": "$pbkdf2-sha256$existing-hash" if configured else None,
        }
        monkeypatch.setattr(
            "app.blueprints.main_routes.load_config", lambda: config_state
        )
        # Stub auth.load_config because /setup goes through @app.before_request
        # rate-limiting which does not auth-check, but verify_password may still
        # trigger via the auth handler for unrelated requests in the loop.
        monkeypatch.setattr(
            "app.auth.load_config", lambda: config_state
        )
        # Capture writes so we don't touch the real config file.
        captured = {}

        def fake_update(fields):
            captured.update(fields)
            return True

        monkeypatch.setattr(
            "app.blueprints.main_routes.update_config_fields", fake_update
        )
        # Avoid action_logger side-effects.
        monkeypatch.setattr(
            "app.blueprints.main_routes.log_user_action",
            lambda *a, **kw: None,
        )

        client = isolated_web_app.test_client()
        return (
            client.post(
                "/setup",
                data={"password": password, "confirm_password": password},
            ),
            captured,
        )

    def test_short_password_rejected_with_length_error(
        self, isolated_web_app, monkeypatch
    ):
        # 11 chars → fails the >=12 rule.
        resp, _ = self._post_setup(
            isolated_web_app, monkeypatch, password="Aa1!Aa1!Aa1"
        )
        assert resp.status_code == 200  # endpoint always returns JSON 200
        body = resp.get_json()
        assert body["success"] is False
        assert "at least 12 characters" in body["error"].lower()

    def test_low_complexity_password_rejected(self, isolated_web_app, monkeypatch):
        # 13 chars but only 2 classes (lowercase + symbol).
        resp, _ = self._post_setup(
            isolated_web_app, monkeypatch, password="alllowercase!"
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "at least three" in body["error"].lower()

    def test_strong_password_accepted(self, isolated_web_app, monkeypatch):
        # 12 chars, 3 classes (lowercase + uppercase + digit).
        resp, captured = self._post_setup(
            isolated_web_app, monkeypatch, password="Lowercase12!"
        )
        body = resp.get_json()
        assert body["success"] is True, f"unexpected error: {body}"
        # Hash + admin user must have been written through update_config_fields.
        assert "web_ui_password_hash" in captured
        assert captured.get("web_ui_user") == "admin"

    def test_setup_rejected_when_already_configured(
        self, isolated_web_app, monkeypatch
    ):
        resp, captured = self._post_setup(
            isolated_web_app,
            monkeypatch,
            password="Lowercase12!",
            configured=True,
        )
        body = resp.get_json()
        assert body["success"] is False
        assert "not allowed" in body["error"].lower()
        # Must NOT have written anything.
        assert captured == {}


# ---------------------------------------------------------------------------
# 3) Session idle timeout configuration
# ---------------------------------------------------------------------------


class TestSessionIdleTimeoutConfig:
    """`_SESSION_IDLE_TIMEOUT_SECONDS` is computed at import time from env."""

    def _reload_security(self):
        import app.web.security as security_mod

        return importlib.reload(security_mod)

    def test_default_is_1800_seconds(self, monkeypatch):
        monkeypatch.delenv("DDC_SESSION_IDLE_TIMEOUT", raising=False)
        mod = self._reload_security()
        assert mod._SESSION_IDLE_TIMEOUT_SECONDS == 1800

    def test_env_override_is_applied(self, monkeypatch):
        monkeypatch.setenv("DDC_SESSION_IDLE_TIMEOUT", "900")
        mod = self._reload_security()
        assert mod._SESSION_IDLE_TIMEOUT_SECONDS == 900

    def test_value_below_floor_clamps_to_60(self, monkeypatch):
        monkeypatch.setenv("DDC_SESSION_IDLE_TIMEOUT", "5")
        mod = self._reload_security()
        assert mod._SESSION_IDLE_TIMEOUT_SECONDS == 60

    def test_invalid_env_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("DDC_SESSION_IDLE_TIMEOUT", "abc")
        mod = self._reload_security()
        assert mod._SESSION_IDLE_TIMEOUT_SECONDS == 1800


# ---------------------------------------------------------------------------
# 4) /logout endpoint
# ---------------------------------------------------------------------------


class TestLogoutEndpoint:
    """/logout always returns 401 + WWW-Authenticate and clears the session."""

    def test_logout_returns_401_with_dynamic_realm(self, isolated_web_app):
        client = isolated_web_app.test_client()
        resp = client.post("/logout")
        assert resp.status_code == 401
        www = resp.headers.get("WWW-Authenticate", "")
        assert www.startswith('Basic realm="DDC-logout-')
        assert www.endswith('"')

    def test_logout_clears_session_keys(self, isolated_web_app):
        client = isolated_web_app.test_client()

        # Pre-seed a session as if the user had been active.
        with client.session_transaction() as sess:
            sess["last_activity"] = time.time()
            sess["setup_mode"] = True
            sess["username"] = "admin"

        resp = client.post("/logout")
        assert resp.status_code == 401

        with client.session_transaction() as sess:
            # session.clear() removes everything; the security
            # before_request hook may add a fresh ``last_activity`` for the
            # /logout request itself, but since /logout is in
            # ``_IDLE_EXEMPT_PATHS`` it is skipped — assert no session data
            # leaked through.
            assert "setup_mode" not in sess
            assert "username" not in sess
            assert "last_activity" not in sess

    def test_logout_get_also_returns_401(self, isolated_web_app):
        # The route accepts GET as well — both must produce the 401 contract.
        client = isolated_web_app.test_client()
        resp = client.get("/logout")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers


# ---------------------------------------------------------------------------
# 5) Setup rate limiter
# ---------------------------------------------------------------------------


class TestSetupRateLimiter:
    """SimpleRateLimiter at limit=5/per_seconds=60 is per-IP and time-based."""

    def _make(self, limit=5, per_seconds=60):
        from app.auth import SimpleRateLimiter

        return SimpleRateLimiter(limit=limit, per_seconds=per_seconds)

    def test_first_five_requests_allowed_then_sixth_blocked(self):
        limiter = self._make()
        ip = "10.0.0.42"
        for i in range(5):
            assert limiter.is_rate_limited(ip) is False, f"req {i + 1} should pass"
        # 6th in the same window must trigger rate-limit.
        assert limiter.is_rate_limited(ip) is True

    def test_different_ips_have_independent_buckets(self):
        limiter = self._make()
        ip_a = "203.0.113.1"
        ip_b = "203.0.113.2"
        # Exhaust IP A.
        for _ in range(5):
            assert limiter.is_rate_limited(ip_a) is False
        assert limiter.is_rate_limited(ip_a) is True
        # IP B is still fresh.
        assert limiter.is_rate_limited(ip_b) is False

    def test_window_expiry_re_allows_requests(self, monkeypatch):
        """After window expires, prior timestamps are pruned and limit resets."""
        limiter = self._make()
        ip = "198.51.100.7"

        # Fill the bucket "now".
        for _ in range(5):
            assert limiter.is_rate_limited(ip) is False
        assert limiter.is_rate_limited(ip) is True

        # Simulate time advancing past the 60-second window by rewriting the
        # stored timestamps to be older than `window`.
        old = datetime.now(timezone.utc) - timedelta(seconds=120)
        with limiter.lock:
            limiter.ip_dict[ip] = [old for _ in limiter.ip_dict[ip]]

        # cleanup happens inside is_rate_limited — old entries should be purged.
        assert limiter.is_rate_limited(ip) is False

    def test_module_level_setup_limiter_is_5_per_60(self):
        """Production constant must remain tight (5 req/min) for /setup."""
        from app.auth import setup_limiter

        assert setup_limiter.limit == 5
        assert setup_limiter.window == 60
