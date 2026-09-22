# -*- coding: utf-8 -*-
"""
THE FINDING (review C42, section 33 F3): the translation test endpoint reports
a key that cannot be DECRYPTED as a key that was never CONFIGURED.

    try:
        fernet = config_service._get_encryption_key()
        api_key = fernet.decrypt(stored.encode()).decode()
    except Exception:
        pass
    ...
    if not api_key:
        return jsonify({'success': False, 'error': 'No API key configured'}), 400

The operator entered a key. The panel says there is none. The real reason - the
encryption key file changed, or the stored value is corrupt - is thrown away by
a bare `except Exception: pass`, with nothing in the log.

This became sharper with review C27: `_get_encryption_key()` now raises
`TranslationKeyUnreadable` with a message that says exactly what to do about
it. This handler would have swallowed that message and answered "no key
configured" instead.

The counter-checks keep the two other answers: a key that really is missing is
still reported as missing, and a key that decrypts is still used.
"""

import json

import pytest
from flask import Flask

from app.blueprints import translation_routes as routes
from services.translation.translation_config_service import (
    TranslationKeyUnreadable,
    TranslationSettings,
)


class _ConfigService:
    def __init__(self, stored, key_error=None, plain=None):
        self._stored = stored
        self._key_error = key_error
        self._plain = plain

    def get_settings(self):
        settings = TranslationSettings()
        settings.api_key_encrypted = self._stored
        settings.api_key_env = "DDC_SPEC_NO_SUCH_ENV"
        settings.provider = "deepl"
        return settings

    def _get_encryption_key(self):
        if self._key_error:
            raise self._key_error

        class _Fernet:
            @staticmethod
            def decrypt(value):
                return _plain_bytes

        _plain_bytes = (self._plain or "").encode()
        return _Fernet()


@pytest.fixture
def client(monkeypatch):
    """The blueprint is registered once at import, so the decorator is already
    baked in - the login check is switched off at the verifier instead."""
    from app.auth import auth as ddc_auth
    monkeypatch.setattr(ddc_auth, "authenticate", lambda *a, **k: "spec", raising=False)
    monkeypatch.setattr(ddc_auth, "get_auth", lambda: type("A", (), {"username": "spec"})(),
                        raising=False)
    monkeypatch.setattr(ddc_auth, "login_required", lambda f: f, raising=False)

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(routes.translation_bp)

    class _NoAuthClient:
        def __init__(self, inner):
            self._inner = inner

        def post(self, *args, **kwargs):
            import base64
            headers = kwargs.setdefault("headers", {})
            headers["Authorization"] = "Basic " + base64.b64encode(
                b"admin:xerxexerxe").decode()
            return self._inner.post(*args, **kwargs)

    return _NoAuthClient(app.test_client())


def _post(client, **kwargs):
    return client.post("/api/translation/test",
                       json={"text": "hello", "target_language": "DE"}, **kwargs)


def test_a_key_that_cannot_be_decrypted_is_not_called_missing(client, monkeypatch):
    """THE FINDING: the operator entered a key; do not claim they did not."""
    monkeypatch.setattr(routes, "get_translation_config_service",
                        lambda: _ConfigService("gAAAAAbroken",
                                               key_error=TranslationKeyUnreadable("key file unreadable")))

    response = _post(client)
    body = json.loads(response.data)

    assert body["success"] is False
    assert "No API key configured" not in body["error"], body["error"]


def test_the_real_reason_reaches_the_log(client, monkeypatch, caplog):
    """A bare `except Exception: pass` threw the only explanation away."""
    import logging
    monkeypatch.setattr(routes, "get_translation_config_service",
                        lambda: _ConfigService("gAAAAAbroken",
                                               key_error=TranslationKeyUnreadable("key file unreadable")))

    with caplog.at_level(logging.DEBUG):
        _post(client)

    assert any("unreadable" in r.getMessage() for r in caplog.records), \
        "nothing in the log says why the key could not be used"


def test_a_key_that_is_really_missing_is_still_missing(client, monkeypatch):
    """COUNTER-CHECK: the other answer keeps its meaning."""
    monkeypatch.setattr(routes, "get_translation_config_service",
                        lambda: _ConfigService(None))

    body = json.loads(_post(client).data)

    assert body["success"] is False
    assert "No API key configured" in body["error"]


def test_a_key_that_decrypts_is_still_used(client, monkeypatch):
    """COUNTER-CHECK: the working path is untouched - it gets past the key
    check and fails later, at the provider, not at the key."""
    monkeypatch.setattr(routes, "get_translation_config_service",
                        lambda: _ConfigService("gAAAAAfine", plain="a-real-key"))
    monkeypatch.setattr(routes, "_api_post", lambda *a, **k: (200, {"translations": [{"text": "hallo"}]}),
                        raising=False)

    body = json.loads(_post(client).data)

    assert "No API key configured" not in (body.get("error") or "")
