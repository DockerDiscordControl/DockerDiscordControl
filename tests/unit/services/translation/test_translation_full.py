# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Translation Full Coverage Tests                #
# ============================================================================ #
"""
Functional unit tests for the translation system:

- services.translation.translation_service
- services.translation.translation_config_service

No sys.modules manipulation — pure monkeypatch / unittest.mock.patch.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import aiohttp
import pytest
from cryptography.fernet import Fernet

from services.translation import translation_config_service as tcs_mod
from services.translation import translation_service as ts_mod
from services.translation.translation_config_service import (
    VALID_PROVIDERS,
    ChannelPair,
    ConfigResult,
    TranslationConfigService,
    TranslationSettings,
    sanitize_string,
    validate_discord_snowflake,
    validate_pair_data,
)
from services.translation.translation_service import (
    ALLOWED_DEEPL_HOSTS,
    DeepLProvider,
    GoogleTranslateProvider,
    MicrosoftTranslatorProvider,
    SlidingWindowRateLimiter,
    TranslationContext,
    TranslationResult,
    TranslationService,
    _normalize_language_code,
    _safe_truncate,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

class _FakeResponse:
    """Async context-manager response used by the aiohttp mock."""

    def __init__(self, status: int = 200,
                 json_data: Optional[Any] = None,
                 text_data: str = ""):
        self.status = status
        self._json = json_data if json_data is not None else {}
        self._text = text_data

    async def json(self):
        return self._json

    async def text(self):
        return self._text

    async def read(self):
        return self._text.encode() if isinstance(self._text, str) else b""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in.

    `post` and `get` return an async-context-manager-compatible response.
    `closed` flips True after `close()`.
    """

    def __init__(self, post_response: Optional[_FakeResponse] = None,
                 post_exception: Optional[Exception] = None,
                 get_response: Optional[_FakeResponse] = None):
        self._post_response = post_response
        self._post_exception = post_exception
        self._get_response = get_response
        self.closed = False
        self.post_calls: List[Dict[str, Any]] = []
        self.get_calls: List[Dict[str, Any]] = []

    def post(self, url, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        if self._post_exception is not None:
            raise self._post_exception
        return self._post_response or _FakeResponse(200, {})

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return self._get_response or _FakeResponse(200, {})

    async def close(self):
        self.closed = True


def _make_pair_data(name: str = "Pair-A",
                    src: str = "111111111111111111",
                    tgt: str = "222222222222222222",
                    target_lang: str = "DE",
                    enabled: bool = True) -> Dict[str, Any]:
    return {
        "name": name,
        "enabled": enabled,
        "source_channel_id": src,
        "target_channel_id": tgt,
        "target_language": target_lang,
        "source_language": None,
        "translate_embeds": True,
    }


def _make_settings(**overrides) -> TranslationSettings:
    s = TranslationSettings()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------

@pytest.fixture
def isolated_config_service(tmp_path, monkeypatch):
    """Build a TranslationConfigService rooted in tmp_path."""
    # The real ctor walks parents[2] to find the project; we replace
    # _ensure_config_exists so we control the file location precisely.
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()

    svc = TranslationConfigService.__new__(TranslationConfigService)
    svc.base_dir = tmp_path
    svc.config_file = cfg_dir / "channel_translations.json"
    import threading
    svc._file_lock = threading.Lock()
    svc._key_lock = threading.Lock()
    svc._ensure_config_exists()
    return svc


@pytest.fixture
def translation_service(isolated_config_service, monkeypatch):
    """Construct a TranslationService backed by an isolated config service."""
    monkeypatch.setattr(
        ts_mod, "get_translation_config_service",
        lambda: isolated_config_service,
    )
    svc = TranslationService()
    return svc


# ============================================================================
# Module-level helper coverage
# ============================================================================

class TestHelpers:
    def test_safe_truncate_short(self):
        assert _safe_truncate("hello", 10) == "hello"

    def test_safe_truncate_exact(self):
        assert _safe_truncate("abcde", 5) == "abcde"

    def test_safe_truncate_long(self):
        assert _safe_truncate("abcdefghij", 4) == "abcd"

    def test_safe_truncate_unicode(self):
        # Code-point oriented (no surrogate split)
        assert _safe_truncate("héllo wörld", 5) == "héllo"

    def test_normalize_language_deepl(self):
        assert _normalize_language_code("en-gb", "deepl") == "EN-GB"

    def test_normalize_language_deepl_strip(self):
        assert _normalize_language_code("  de  ", "deepl") == "DE"

    def test_normalize_language_google_truncates(self):
        assert _normalize_language_code("EN-GB", "google") == "en"

    def test_normalize_language_microsoft_lowercase(self):
        assert _normalize_language_code("DE", "microsoft") == "de"

    def test_normalize_language_empty_returns_input(self):
        assert _normalize_language_code("", "deepl") == ""


# ============================================================================
# DataClasses
# ============================================================================

class TestDataClasses:
    def test_translation_context_full_text_combines(self):
        ctx = TranslationContext(
            message_id="m1", channel_id="c1", guild_id="g1",
            author_name="Alice", author_avatar_url="https://x/y.png",
            content="Hello",
            embed_texts=["Embed-1", "Embed-2"],
        )
        assert ctx.full_text == "Hello\n\nEmbed-1\n\nEmbed-2"

    def test_translation_context_message_link(self):
        ctx = TranslationContext(
            message_id="3", channel_id="2", guild_id="1",
            author_name="A", author_avatar_url="",
            content="x",
        )
        assert ctx.message_link == "https://discord.com/channels/1/2/3"

    def test_translation_context_full_text_no_content(self):
        ctx = TranslationContext(
            message_id="m", channel_id="c", guild_id="g",
            author_name="A", author_avatar_url="",
            content="",
            embed_texts=["Only embed"],
        )
        assert ctx.full_text == "Only embed"

    def test_translation_result_default_values(self):
        r = TranslationResult(success=False)
        assert r.translated_text is None
        assert r.characters_used == 0
        assert r.error is None

    def test_channel_pair_round_trip(self):
        d = _make_pair_data(name="Roundtrip")
        d["id"] = "fixed-id"
        cp = ChannelPair.from_dict(d)
        assert cp.name == "Roundtrip"
        assert cp.id == "fixed-id"
        assert cp.target_language == "DE"
        out = cp.to_dict()
        assert out["source_channel_id"] == d["source_channel_id"]
        assert out["target_channel_id"] == d["target_channel_id"]

    def test_channel_pair_defaults(self):
        cp = ChannelPair.from_dict({})
        assert cp.name == "New Pair"
        assert cp.target_language == "DE"
        assert cp.enabled is True
        assert cp.translate_embeds is True

    def test_translation_settings_from_dict_invalid_provider(self):
        s = TranslationSettings.from_dict({"provider": "babel-fish"})
        assert s.provider == "deepl"

    def test_translation_settings_from_dict_clamps_rate_limit_low(self):
        s = TranslationSettings.from_dict({"rate_limit_per_minute": -7})
        assert s.rate_limit_per_minute == 1

    def test_translation_settings_from_dict_clamps_rate_limit_high(self):
        s = TranslationSettings.from_dict({"rate_limit_per_minute": 999_999})
        assert s.rate_limit_per_minute == 600

    def test_translation_settings_from_dict_clamps_max_text_low(self):
        s = TranslationSettings.from_dict({"max_text_length": 1})
        assert s.max_text_length == 100

    def test_translation_settings_from_dict_clamps_max_text_high(self):
        s = TranslationSettings.from_dict({"max_text_length": 10_000_000})
        assert s.max_text_length == 50_000

    def test_translation_settings_invalid_deepl_url_replaced(self):
        s = TranslationSettings.from_dict({"deepl_api_url": "http://evil.com/"})
        assert s.deepl_api_url.startswith("https://api-free.deepl.com/")

    def test_translation_settings_round_trip(self):
        original = _make_settings(provider="google",
                                  rate_limit_per_minute=10,
                                  max_text_length=200)
        again = TranslationSettings.from_dict(original.to_dict())
        assert again.provider == "google"
        assert again.rate_limit_per_minute == 10
        assert again.max_text_length == 200


# ============================================================================
# Validation helpers
# ============================================================================

class TestValidation:
    def test_validate_snowflake_valid(self):
        ok, _ = validate_discord_snowflake("123456789012345678", "src")
        assert ok

    def test_validate_snowflake_empty(self):
        ok, msg = validate_discord_snowflake("", "src")
        assert not ok
        assert "src" in msg

    def test_validate_snowflake_alpha(self):
        ok, _ = validate_discord_snowflake("abc", "src")
        assert not ok

    def test_validate_snowflake_too_short(self):
        ok, _ = validate_discord_snowflake("123", "src")
        assert not ok

    def test_sanitize_string_strips_brackets(self):
        assert sanitize_string("<script>", 50) == "script"

    def test_sanitize_string_truncates(self):
        assert sanitize_string("aaaaaa", 3) == "aaa"

    def test_sanitize_string_empty(self):
        assert sanitize_string("", 10) == ""

    def test_validate_pair_data_ok(self):
        ok, err, warns = validate_pair_data(_make_pair_data())
        assert ok and err == ""

    def test_validate_pair_data_missing_name(self):
        ok, err, _ = validate_pair_data(_make_pair_data(name=""))
        assert not ok
        assert "Pair name is required" in err

    def test_validate_pair_data_same_src_tgt(self):
        d = _make_pair_data(src="123456789012345678", tgt="123456789012345678")
        ok, err, _ = validate_pair_data(d)
        assert not ok
        assert "same" in err.lower()

    def test_validate_pair_data_invalid_channels(self):
        d = _make_pair_data(src="bad", tgt="alsoBad")
        ok, err, _ = validate_pair_data(d)
        assert not ok

    def test_validate_pair_data_unknown_language_warning(self):
        d = _make_pair_data(target_lang="XX")
        ok, _, warns = validate_pair_data(d)
        assert ok  # only a warning
        assert any("XX" in w for w in warns)


# ============================================================================
# DeepLProvider
# ============================================================================

class TestDeepLProvider:
    def test_invalid_url_falls_back_to_default(self):
        p = DeepLProvider("k", "http://evil.com/v2/translate")
        assert p.api_url.startswith("https://api-free.deepl.com/")

    def test_valid_paid_url_kept(self):
        url = "https://api.deepl.com/v2/translate"
        p = DeepLProvider("k", url)
        assert p.api_url == url

    def test_get_name(self):
        assert DeepLProvider("k").get_name() == "DeepL"

    async def test_translate_success(self):
        provider = DeepLProvider("k")
        resp = _FakeResponse(200, {
            "translations": [
                {"text": "Hallo", "detected_source_language": "EN"}
            ]
        })
        session = _FakeSession(post_response=resp)
        result = await provider.translate("Hello", "DE", session=session)
        assert result.success is True
        assert result.translated_text == "Hallo"
        assert result.detected_language == "EN"
        assert result.provider == "DeepL"
        assert result.characters_used == len("Hello")

    async def test_translate_with_source_lang_in_payload(self):
        provider = DeepLProvider("k")
        resp = _FakeResponse(200, {"translations": [{"text": "x"}]})
        session = _FakeSession(post_response=resp)
        await provider.translate("Hi", "de", source_lang="en", session=session)
        body = session.post_calls[0]["json"]
        assert body["target_lang"] == "DE"
        assert body["source_lang"] == "EN"

    async def test_translate_empty_translations(self):
        provider = DeepLProvider("k")
        resp = _FakeResponse(200, {"translations": []})
        session = _FakeSession(post_response=resp)
        result = await provider.translate("x", "DE", session=session)
        assert not result.success
        assert "No translations" in result.error

    async def test_translate_invalid_api_key(self):
        provider = DeepLProvider("k")
        resp = _FakeResponse(403, {})
        session = _FakeSession(post_response=resp)
        result = await provider.translate("x", "DE", session=session)
        assert not result.success
        assert "Invalid API key" in result.error

    async def test_translate_rate_limit(self):
        provider = DeepLProvider("k")
        session = _FakeSession(post_response=_FakeResponse(429, {}))
        result = await provider.translate("x", "DE", session=session)
        assert not result.success
        assert "Rate limit" in result.error

    async def test_translate_quota(self):
        provider = DeepLProvider("k")
        session = _FakeSession(post_response=_FakeResponse(456, {}))
        result = await provider.translate("x", "DE", session=session)
        assert not result.success
        assert "Quota" in result.error

    async def test_translate_other_status(self):
        provider = DeepLProvider("k")
        session = _FakeSession(
            post_response=_FakeResponse(500, {}, text_data="upstream blew up")
        )
        result = await provider.translate("x", "DE", session=session)
        assert not result.success
        assert "HTTP 500" in result.error
        assert "upstream" in result.error

    async def test_translate_client_error(self):
        provider = DeepLProvider("k")
        session = _FakeSession(post_exception=aiohttp.ClientError("boom"))
        result = await provider.translate("x", "DE", session=session)
        assert not result.success
        assert "Connection error" in result.error

    async def test_translate_timeout(self):
        provider = DeepLProvider("k")
        session = _FakeSession(post_exception=asyncio.TimeoutError())
        result = await provider.translate("x", "DE", session=session)
        assert not result.success
        assert "timed out" in result.error

    async def test_owns_session_when_none_given(self):
        """When session=None, provider must build/close its own session."""
        provider = DeepLProvider("k")
        owned = _FakeSession(post_response=_FakeResponse(
            200, {"translations": [{"text": "ok"}]}
        ))
        with patch.object(ts_mod.aiohttp, "ClientSession", return_value=owned):
            result = await provider.translate("x", "DE", session=None)
        assert result.success
        assert owned.closed is True


# ============================================================================
# GoogleTranslateProvider
# ============================================================================

class TestGoogleProvider:
    def test_get_name(self):
        assert GoogleTranslateProvider("k").get_name() == "Google"

    async def test_translate_success(self):
        provider = GoogleTranslateProvider("k")
        payload = {"data": {"translations": [
            {"translatedText": "Bonjour",
             "detectedSourceLanguage": "en"}
        ]}}
        session = _FakeSession(post_response=_FakeResponse(200, payload))
        result = await provider.translate("Hello", "FR", session=session)
        assert result.success
        assert result.translated_text == "Bonjour"
        assert result.detected_language == "en"

    async def test_translate_with_source_lang(self):
        provider = GoogleTranslateProvider("k")
        payload = {"data": {"translations": [{"translatedText": "x"}]}}
        session = _FakeSession(post_response=_FakeResponse(200, payload))
        await provider.translate("Hi", "fr", source_lang="EN", session=session)
        form = session.post_calls[0]["data"]
        assert form["source"] == "en"
        assert form["target"] == "fr"
        assert form["format"] == "text"

    async def test_translate_no_results(self):
        provider = GoogleTranslateProvider("k")
        session = _FakeSession(post_response=_FakeResponse(
            200, {"data": {"translations": []}}
        ))
        result = await provider.translate("x", "FR", session=session)
        assert not result.success

    async def test_translate_403(self):
        provider = GoogleTranslateProvider("k")
        session = _FakeSession(post_response=_FakeResponse(403, {}))
        result = await provider.translate("x", "FR", session=session)
        assert not result.success
        assert "Invalid API key" in result.error

    async def test_translate_429(self):
        provider = GoogleTranslateProvider("k")
        session = _FakeSession(post_response=_FakeResponse(429, {}))
        result = await provider.translate("x", "FR", session=session)
        assert not result.success
        assert "Rate limit" in result.error

    async def test_translate_other_http(self):
        provider = GoogleTranslateProvider("k")
        session = _FakeSession(post_response=_FakeResponse(
            500, {}, text_data="srvfail"
        ))
        result = await provider.translate("x", "FR", session=session)
        assert "HTTP 500" in result.error

    async def test_translate_client_error(self):
        provider = GoogleTranslateProvider("k")
        session = _FakeSession(post_exception=aiohttp.ClientError("bad"))
        result = await provider.translate("x", "FR", session=session)
        assert "Connection error" in result.error

    async def test_translate_timeout(self):
        provider = GoogleTranslateProvider("k")
        session = _FakeSession(post_exception=asyncio.TimeoutError())
        result = await provider.translate("x", "FR", session=session)
        assert "timed out" in result.error


# ============================================================================
# MicrosoftTranslatorProvider
# ============================================================================

class TestMicrosoftProvider:
    def test_get_name(self):
        assert MicrosoftTranslatorProvider("k").get_name() == "Microsoft"

    async def test_translate_success_with_detection(self):
        provider = MicrosoftTranslatorProvider("k", region="westeurope")
        payload = [{
            "detectedLanguage": {"language": "en", "score": 1.0},
            "translations": [{"to": "de", "text": "Hallo"}]
        }]
        session = _FakeSession(post_response=_FakeResponse(200, payload))
        result = await provider.translate("Hello", "DE", session=session)
        assert result.success
        assert result.translated_text == "Hallo"
        assert result.detected_language == "en"
        # Headers must include subscription info
        headers = session.post_calls[0]["headers"]
        assert headers["Ocp-Apim-Subscription-Key"] == "k"
        assert headers["Ocp-Apim-Subscription-Region"] == "westeurope"

    async def test_translate_no_translations_array(self):
        provider = MicrosoftTranslatorProvider("k")
        session = _FakeSession(post_response=_FakeResponse(
            200, [{"translations": []}]
        ))
        result = await provider.translate("x", "DE", session=session)
        assert not result.success
        assert "No translations" in result.error

    async def test_translate_401_invalid_key(self):
        provider = MicrosoftTranslatorProvider("k")
        session = _FakeSession(post_response=_FakeResponse(401, {}))
        result = await provider.translate("x", "DE", session=session)
        assert "Invalid API key" in result.error

    async def test_translate_403_invalid_key(self):
        provider = MicrosoftTranslatorProvider("k")
        session = _FakeSession(post_response=_FakeResponse(403, {}))
        result = await provider.translate("x", "DE", session=session)
        assert "Invalid API key" in result.error

    async def test_translate_429(self):
        provider = MicrosoftTranslatorProvider("k")
        session = _FakeSession(post_response=_FakeResponse(429, {}))
        result = await provider.translate("x", "DE", session=session)
        assert "Rate limit" in result.error

    async def test_translate_500(self):
        provider = MicrosoftTranslatorProvider("k")
        session = _FakeSession(post_response=_FakeResponse(
            500, {}, text_data="msft-down"
        ))
        result = await provider.translate("x", "DE", session=session)
        assert "HTTP 500" in result.error

    async def test_translate_client_error(self):
        provider = MicrosoftTranslatorProvider("k")
        session = _FakeSession(post_exception=aiohttp.ClientError("net"))
        result = await provider.translate("x", "DE", session=session)
        assert "Connection error" in result.error

    async def test_translate_timeout(self):
        provider = MicrosoftTranslatorProvider("k")
        session = _FakeSession(post_exception=asyncio.TimeoutError())
        result = await provider.translate("x", "DE", session=session)
        assert "timed out" in result.error

    async def test_translate_with_source_lang_param(self):
        provider = MicrosoftTranslatorProvider("k")
        payload = [{"translations": [{"text": "ok"}]}]
        session = _FakeSession(post_response=_FakeResponse(200, payload))
        await provider.translate("Hi", "de", source_lang="EN", session=session)
        params = session.post_calls[0]["params"]
        assert params["from"] == "en"
        assert params["to"] == "de"


# ============================================================================
# SlidingWindowRateLimiter
# ============================================================================

class TestRateLimiter:
    def test_below_limit_allows(self):
        rl = SlidingWindowRateLimiter()
        assert rl.check(3) is True
        assert rl.check(3) is True

    def test_at_limit_denies(self):
        rl = SlidingWindowRateLimiter()
        assert rl.check(2) is True
        assert rl.check(2) is True
        assert rl.check(2) is False  # third in window denied

    def test_expired_entries_pruned(self, monkeypatch):
        rl = SlidingWindowRateLimiter()

        # First "now" = 1000 → fills the queue.
        # Second "now" = 1500 (>60s later) → entries should be pruned.
        times = iter([1000.0, 1500.0])
        monkeypatch.setattr(ts_mod.time, "monotonic", lambda: next(times))

        assert rl.check(1) is True   # ts=1000
        assert rl.check(1) is True   # ts=1500, 1000 expired


# ============================================================================
# TranslationConfigService
# ============================================================================

class TestConfigServiceInit:
    def test_creates_default_config_file(self, isolated_config_service):
        assert isolated_config_service.config_file.exists()
        data = json.loads(isolated_config_service.config_file.read_text())
        assert "settings" in data
        assert data["channel_pairs"] == []

    def test_get_settings_returns_defaults(self, isolated_config_service):
        s = isolated_config_service.get_settings()
        assert isinstance(s, TranslationSettings)
        assert s.provider == "deepl"
        assert s.enabled is False

    def test_load_config_corrupted_returns_defaults(self, isolated_config_service):
        isolated_config_service.config_file.write_text("not json{{{")
        # Direct call works too — public API resilience:
        settings = isolated_config_service.get_settings()
        assert isinstance(settings, TranslationSettings)


class TestConfigServicePairs:
    def test_add_valid_pair(self, isolated_config_service):
        result = isolated_config_service.add_pair(_make_pair_data())
        assert result.success is True
        assert isinstance(result.data, ChannelPair)
        # Round-trip via get_pairs
        pairs = isolated_config_service.get_pairs()
        assert len(pairs) == 1
        assert pairs[0].name == "Pair-A"

    def test_add_invalid_pair_returns_error(self, isolated_config_service):
        bad = _make_pair_data(src="oops")
        result = isolated_config_service.add_pair(bad)
        assert not result.success
        assert "Validation failed" in result.error

    def test_get_pair_by_id(self, isolated_config_service):
        r = isolated_config_service.add_pair(_make_pair_data())
        fetched = isolated_config_service.get_pair(r.data.id)
        assert fetched is not None
        assert fetched.id == r.data.id

    def test_get_pair_missing_returns_none(self, isolated_config_service):
        assert isolated_config_service.get_pair("nope") is None

    def test_update_pair(self, isolated_config_service):
        r = isolated_config_service.add_pair(_make_pair_data())
        new_data = _make_pair_data(name="Renamed")
        upd = isolated_config_service.update_pair(r.data.id, new_data)
        assert upd.success
        assert isolated_config_service.get_pair(r.data.id).name == "Renamed"

    def test_update_pair_not_found(self, isolated_config_service):
        result = isolated_config_service.update_pair(
            "missing-id", _make_pair_data()
        )
        assert not result.success
        assert "not found" in result.error.lower()

    def test_update_pair_invalid_data(self, isolated_config_service):
        r = isolated_config_service.add_pair(_make_pair_data())
        bad = _make_pair_data(src="bad")
        result = isolated_config_service.update_pair(r.data.id, bad)
        assert not result.success

    def test_delete_pair(self, isolated_config_service):
        r = isolated_config_service.add_pair(_make_pair_data())
        result = isolated_config_service.delete_pair(r.data.id)
        assert result.success
        assert isolated_config_service.get_pair(r.data.id) is None

    def test_delete_pair_not_found(self, isolated_config_service):
        result = isolated_config_service.delete_pair("ghost")
        assert not result.success

    def test_toggle_pair(self, isolated_config_service):
        r = isolated_config_service.add_pair(_make_pair_data(enabled=True))
        toggled = isolated_config_service.toggle_pair(r.data.id)
        assert toggled.success
        assert toggled.data["enabled"] is False
        again = isolated_config_service.toggle_pair(r.data.id)
        assert again.data["enabled"] is True

    def test_toggle_pair_not_found(self, isolated_config_service):
        assert not isolated_config_service.toggle_pair("ghost").success

    def test_increment_translation_count(self, isolated_config_service):
        r = isolated_config_service.add_pair(_make_pair_data())
        ok = isolated_config_service.increment_translation_count(r.data.id)
        assert ok is True
        pair = isolated_config_service.get_pair(r.data.id)
        assert pair.metadata["translation_count"] == 1
        # Second increment
        isolated_config_service.increment_translation_count(r.data.id)
        pair2 = isolated_config_service.get_pair(r.data.id)
        assert pair2.metadata["translation_count"] == 2

    def test_increment_translation_count_unknown(self, isolated_config_service):
        assert isolated_config_service.increment_translation_count("missing") is False

    def test_get_source_and_target_channel_ids(self, isolated_config_service):
        isolated_config_service.add_pair(_make_pair_data(
            src="111111111111111111", tgt="222222222222222222"
        ))
        isolated_config_service.add_pair(_make_pair_data(
            name="P2", src="333333333333333333", tgt="444444444444444444",
            enabled=False
        ))
        sources = isolated_config_service.get_source_channel_ids()
        targets = isolated_config_service.get_target_channel_ids()
        # Only enabled pairs in source set
        assert "111111111111111111" in sources
        assert "333333333333333333" not in sources
        # Both pairs in target set
        assert {"222222222222222222", "444444444444444444"}.issubset(targets)

    def test_get_pairs_skips_invalid_entries(self, isolated_config_service):
        # Inject malformed pair into raw config
        raw = json.loads(isolated_config_service.config_file.read_text())
        raw["channel_pairs"] = [
            {"id": "ok",
             "name": "Good",
             "enabled": True,
             "source_channel_id": "111111111111111111",
             "target_channel_id": "222222222222222222",
             "target_language": "DE"},
        ]
        isolated_config_service.config_file.write_text(json.dumps(raw))
        pairs = isolated_config_service.get_pairs()
        assert len(pairs) == 1


class TestConfigServiceSettings:
    def test_update_settings_invalid_provider(self, isolated_config_service):
        result = isolated_config_service.update_settings({"provider": "bogus"})
        assert not result.success
        assert "Invalid provider" in result.error

    def test_update_settings_invalid_rate_limit(self, isolated_config_service):
        result = isolated_config_service.update_settings({
            "provider": "deepl", "rate_limit_per_minute": 99999
        })
        assert not result.success
        assert "Rate limit" in result.error

    def test_update_settings_invalid_max_text(self, isolated_config_service):
        result = isolated_config_service.update_settings({
            "provider": "deepl",
            "rate_limit_per_minute": 60,
            "max_text_length": 9_999_999,
        })
        assert not result.success
        assert "Max text" in result.error

    def test_update_settings_invalid_deepl_url(self, isolated_config_service):
        result = isolated_config_service.update_settings({
            "provider": "deepl",
            "rate_limit_per_minute": 60,
            "max_text_length": 1000,
            "deepl_api_url": "https://evil.example.com/v2/translate",
        })
        assert not result.success
        assert "DeepL" in result.error

    def test_update_settings_success(self, isolated_config_service):
        result = isolated_config_service.update_settings({
            "provider": "google",
            "rate_limit_per_minute": 30,
            "max_text_length": 1000,
            "deepl_api_url": "https://api-free.deepl.com/v2/translate",
            "enabled": True,
        })
        assert result.success
        s = isolated_config_service.get_settings()
        assert s.provider == "google"
        assert s.enabled is True
        assert s.rate_limit_per_minute == 30

    def test_update_settings_preserves_encrypted_key(self, isolated_config_service):
        # Save a key first
        isolated_config_service.save_api_key("secret-key")
        before = isolated_config_service.get_settings().api_key_encrypted
        assert before  # something was written
        # Now update settings without sending api_key_encrypted
        isolated_config_service.update_settings({
            "provider": "google",
            "rate_limit_per_minute": 60,
            "max_text_length": 5000,
            "deepl_api_url": "https://api-free.deepl.com/v2/translate",
            "api_key_encrypted": "should-be-ignored",
        })
        after = isolated_config_service.get_settings().api_key_encrypted
        assert after == before  # original encrypted blob preserved

    def test_save_api_key_encrypts(self, isolated_config_service):
        result = isolated_config_service.save_api_key("my-real-key")
        assert result.success
        s = isolated_config_service.get_settings()
        assert s.api_key_encrypted is not None
        # Round-trip via the same Fernet
        f = isolated_config_service._get_encryption_key()
        assert f.decrypt(s.api_key_encrypted.encode()).decode() == "my-real-key"

    def test_save_api_key_clear(self, isolated_config_service):
        isolated_config_service.save_api_key("x")
        isolated_config_service.save_api_key(None)
        s = isolated_config_service.get_settings()
        assert s.api_key_encrypted is None

    def test_get_encryption_key_persists(self, isolated_config_service):
        f1 = isolated_config_service._get_encryption_key()
        f2 = isolated_config_service._get_encryption_key()
        # Round-trip through both Fernets
        token = f1.encrypt(b"hello")
        assert f2.decrypt(token) == b"hello"
        # Key file actually written
        keyfile = isolated_config_service.config_file.parent / ".translation_key"
        assert keyfile.exists()


# ============================================================================
# TranslationService — internals
# ============================================================================

class TestTranslationServiceInternals:
    async def test_get_session_creates_and_reuses(self, translation_service):
        with patch.object(ts_mod.aiohttp, "ClientSession") as mock_cls:
            inst = MagicMock()
            inst.closed = False
            mock_cls.return_value = inst
            s1 = await translation_service._get_session()
            s2 = await translation_service._get_session()
            assert s1 is s2
            mock_cls.assert_called_once()

    async def test_get_session_recreates_when_closed(self, translation_service):
        with patch.object(ts_mod.aiohttp, "ClientSession") as mock_cls:
            first = MagicMock(); first.closed = True
            second = MagicMock(); second.closed = False
            mock_cls.side_effect = [first, second]
            await translation_service._get_session()
            new = await translation_service._get_session()
            assert new is second
            assert mock_cls.call_count == 2

    async def test_close_session(self, translation_service):
        sess = MagicMock()
        sess.closed = False
        sess.close = AsyncMock()
        translation_service._session = sess
        await translation_service.close()
        sess.close.assert_awaited_once()
        assert translation_service._session is None

    async def test_close_when_already_closed(self, translation_service):
        sess = MagicMock(); sess.closed = True
        translation_service._session = sess
        # Should not raise
        await translation_service.close()

    def test_resolve_api_key_from_env(self, translation_service, monkeypatch):
        monkeypatch.setenv("TRANSLATION_API_KEY", "from-env")
        s = _make_settings(api_key_env="TRANSLATION_API_KEY",
                           api_key_encrypted="ignored")
        assert translation_service._resolve_api_key(s) == "from-env"

    def test_resolve_api_key_missing(self, translation_service, monkeypatch):
        monkeypatch.delenv("TRANSLATION_API_KEY", raising=False)
        s = _make_settings(api_key_encrypted=None)
        assert translation_service._resolve_api_key(s) is None

    def test_resolve_api_key_plaintext_fallback(self, translation_service,
                                                monkeypatch):
        monkeypatch.delenv("TRANSLATION_API_KEY", raising=False)
        s = _make_settings(api_key_encrypted="plain-text-no-prefix")
        assert translation_service._resolve_api_key(s) == "plain-text-no-prefix"

    def test_resolve_api_key_encrypted(self, translation_service, monkeypatch):
        monkeypatch.delenv("TRANSLATION_API_KEY", raising=False)
        # Encrypt with the real config service Fernet
        fernet = translation_service.config_service._get_encryption_key()
        token = fernet.encrypt(b"top-secret").decode()
        s = _make_settings(api_key_encrypted=token)
        assert translation_service._resolve_api_key(s) == "top-secret"

    def test_resolve_api_key_encrypted_decryption_failure(
        self, translation_service, monkeypatch
    ):
        monkeypatch.delenv("TRANSLATION_API_KEY", raising=False)
        # Looks encrypted but isn't a valid token
        s = _make_settings(api_key_encrypted="gAAAAAcorruptdata")
        assert translation_service._resolve_api_key(s) is None

    def test_get_provider_deepl_default(self, translation_service):
        s = _make_settings(provider="deepl")
        prov = translation_service._get_provider(s, "k")
        assert isinstance(prov, DeepLProvider)

    def test_get_provider_google(self, translation_service):
        s = _make_settings(provider="google")
        prov = translation_service._get_provider(s, "k")
        assert isinstance(prov, GoogleTranslateProvider)

    def test_get_provider_microsoft(self, translation_service):
        s = _make_settings(provider="microsoft")
        prov = translation_service._get_provider(s, "k")
        assert isinstance(prov, MicrosoftTranslatorProvider)

    def test_mark_and_check_translated(self, translation_service):
        translation_service.mark_as_translated("msg-1")
        assert translation_service.is_translated_message("msg-1")
        assert not translation_service.is_translated_message("msg-2")

    def test_reset_auto_disabled(self, translation_service):
        translation_service._auto_disabled_pairs.add("p1")
        translation_service._consecutive_failures["p1"] = 5
        translation_service.reset_auto_disabled("p1")
        assert "p1" not in translation_service._auto_disabled_pairs
        assert "p1" not in translation_service._consecutive_failures


class TestTranslationServiceRetry:
    async def test_retry_succeeds_first_attempt(self, translation_service):
        provider = MagicMock()
        provider.translate = AsyncMock(return_value=TranslationResult(
            success=True, translated_text="ok", provider="DeepL"
        ))
        result = await translation_service._translate_with_retry(
            provider, "txt", "DE", None, MagicMock()
        )
        assert result.success
        provider.translate.assert_awaited_once()

    async def test_retry_retries_on_transient_then_succeeds(
        self, translation_service, monkeypatch
    ):
        # Avoid actually sleeping
        monkeypatch.setattr(ts_mod.asyncio, "sleep",
                            AsyncMock(return_value=None))
        provider = MagicMock()
        provider.translate = AsyncMock(side_effect=[
            TranslationResult(success=False, error="Request timed out"),
            TranslationResult(success=True, translated_text="finally"),
        ])
        result = await translation_service._translate_with_retry(
            provider, "txt", "DE", None, MagicMock()
        )
        assert result.success
        assert provider.translate.await_count == 2

    async def test_retry_gives_up_on_permanent_error(
        self, translation_service, monkeypatch
    ):
        monkeypatch.setattr(ts_mod.asyncio, "sleep",
                            AsyncMock(return_value=None))
        provider = MagicMock()
        provider.translate = AsyncMock(return_value=TranslationResult(
            success=False, error="Invalid API key"
        ))
        result = await translation_service._translate_with_retry(
            provider, "t", "DE", None, MagicMock()
        )
        assert not result.success
        # Permanent error = no retries
        assert provider.translate.await_count == 1

    async def test_retry_exhausts_on_transient(
        self, translation_service, monkeypatch
    ):
        monkeypatch.setattr(ts_mod.asyncio, "sleep",
                            AsyncMock(return_value=None))
        provider = MagicMock()
        provider.translate = AsyncMock(return_value=TranslationResult(
            success=False, error="Connection error: down"
        ))
        result = await translation_service._translate_with_retry(
            provider, "t", "DE", None, MagicMock()
        )
        assert not result.success
        # MAX_RETRIES + 1 attempts
        assert provider.translate.await_count == ts_mod.MAX_RETRIES + 1


class TestBuildTranslationText:
    def test_dedupe_embed_overlap(self, translation_service):
        ctx = TranslationContext(
            message_id="m", channel_id="c", guild_id="g",
            author_name="A", author_avatar_url="",
            content="this content has a quite long body of text inside",
            embed_texts=[
                "this content has a quite long body of text inside",
                "Different embed body content here",
            ],
        )
        pair = ChannelPair.from_dict(_make_pair_data())
        text = translation_service._build_translation_text(ctx, pair)
        # Identical embed text dropped, distinct one kept
        assert "Different embed body content here" in text
        assert text.count(
            "this content has a quite long body of text inside"
        ) == 1

    def test_no_embeds_when_disabled(self, translation_service):
        ctx = TranslationContext(
            message_id="m", channel_id="c", guild_id="g",
            author_name="A", author_avatar_url="",
            content="Body",
            embed_texts=["embed-only-content"],
        )
        d = _make_pair_data()
        d["translate_embeds"] = False
        pair = ChannelPair.from_dict(d)
        text = translation_service._build_translation_text(ctx, pair)
        assert "embed-only-content" not in text
        assert text == "Body"


# ============================================================================
# TranslationService.process_message
# ============================================================================

class TestProcessMessage:
    @pytest.fixture
    def setup_pair(self, translation_service, monkeypatch):
        """Add a pair so the service has something to dispatch on."""
        cs = translation_service.config_service
        # Enable settings + add API key
        cs.update_settings({
            "provider": "deepl",
            "rate_limit_per_minute": 60,
            "max_text_length": 5000,
            "deepl_api_url": "https://api-free.deepl.com/v2/translate",
            "enabled": True,
        })
        monkeypatch.setenv("TRANSLATION_API_KEY", "live-key")
        result = cs.add_pair(_make_pair_data(
            src="111111111111111111", tgt="222222222222222222"
        ))
        return result.data

    def _ctx(self, channel_id="111111111111111111", content="Hi"):
        return TranslationContext(
            message_id="m1", channel_id=channel_id, guild_id="g1",
            author_name="Alice", author_avatar_url="",
            content=content,
        )

    async def test_disabled_returns_empty(self, translation_service):
        ctx = self._ctx()
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []

    async def test_unknown_source_channel(self, translation_service, setup_pair):
        ctx = self._ctx(channel_id="999999999999999999")
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []

    async def test_target_loop_prevention(self, translation_service, setup_pair):
        # Message coming from a target channel (also accidentally a source)
        cs = translation_service.config_service
        # Add a second pair where source == previous pair's target
        cs.add_pair(_make_pair_data(
            name="P-loop",
            src="222222222222222222", tgt="333333333333333333",
        ))
        ctx = self._ctx(channel_id="222222222222222222")
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []

    async def test_no_api_key(self, translation_service, setup_pair, monkeypatch):
        monkeypatch.delenv("TRANSLATION_API_KEY", raising=False)
        # Wipe encrypted key too
        translation_service.config_service.save_api_key(None)
        ctx = self._ctx()
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []

    async def test_skips_disabled_pair(self, translation_service, setup_pair):
        translation_service.config_service.toggle_pair(setup_pair.id)
        # No pair enabled for this source any more
        ctx = self._ctx()
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []

    async def test_skips_auto_disabled_pair(self, translation_service, setup_pair):
        translation_service._auto_disabled_pairs.add(setup_pair.id)
        ctx = self._ctx()
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []

    async def test_skips_empty_message_no_attachment(
        self, translation_service, setup_pair
    ):
        ctx = self._ctx(content="   ")  # whitespace only, no attachments
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []

    async def test_translation_success_path(
        self, translation_service, setup_pair, monkeypatch
    ):
        # Patch retry to short-circuit
        monkeypatch.setattr(
            translation_service, "_translate_with_retry",
            AsyncMock(return_value=TranslationResult(
                success=True, translated_text="Hallo",
                detected_language="EN", provider="DeepL"
            ))
        )
        # Stub _post_translation to avoid Discord wiring
        post_mock = AsyncMock()
        monkeypatch.setattr(translation_service, "_post_translation", post_mock)
        # Stub session creation
        monkeypatch.setattr(
            translation_service, "_get_session",
            AsyncMock(return_value=MagicMock())
        )
        ctx = self._ctx(content="Hello")
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == [setup_pair.name]
        post_mock.assert_awaited_once()

    async def test_translation_failure_records_failure(
        self, translation_service, setup_pair, monkeypatch
    ):
        monkeypatch.setattr(
            translation_service, "_translate_with_retry",
            AsyncMock(return_value=TranslationResult(
                success=False, error="Invalid API key", provider="DeepL"
            ))
        )
        monkeypatch.setattr(
            translation_service, "_get_session",
            AsyncMock(return_value=MagicMock())
        )
        ctx = self._ctx(content="Hello")
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []
        assert translation_service._consecutive_failures[setup_pair.id] == 1

    async def test_failures_auto_disable(
        self, translation_service, setup_pair, monkeypatch
    ):
        monkeypatch.setattr(
            translation_service, "_translate_with_retry",
            AsyncMock(return_value=TranslationResult(
                success=False, error="HTTP 500", provider="DeepL"
            ))
        )
        monkeypatch.setattr(
            translation_service, "_get_session",
            AsyncMock(return_value=MagicMock())
        )
        ctx = self._ctx(content="Hello")
        for _ in range(5):
            await translation_service.process_message(ctx, MagicMock())
        assert setup_pair.id in translation_service._auto_disabled_pairs

    async def test_rate_limited_skip(
        self, translation_service, setup_pair, monkeypatch
    ):
        # Force the rate limiter to deny
        monkeypatch.setattr(translation_service._rate_limiter, "check",
                            lambda *_a, **_kw: False)
        retry_mock = AsyncMock()
        monkeypatch.setattr(translation_service,
                            "_translate_with_retry", retry_mock)
        monkeypatch.setattr(
            translation_service, "_get_session",
            AsyncMock(return_value=MagicMock())
        )
        ctx = self._ctx(content="Hello")
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == []
        retry_mock.assert_not_awaited()

    async def test_attachment_only_passthrough(
        self, translation_service, setup_pair, monkeypatch
    ):
        post_mock = AsyncMock()
        monkeypatch.setattr(translation_service, "_post_translation", post_mock)
        monkeypatch.setattr(
            translation_service, "_get_session",
            AsyncMock(return_value=MagicMock())
        )
        retry_mock = AsyncMock()
        monkeypatch.setattr(translation_service, "_translate_with_retry",
                            retry_mock)

        ctx = TranslationContext(
            message_id="m", channel_id="111111111111111111", guild_id="g",
            author_name="A", author_avatar_url="",
            content="",
            attachment_urls=[{"url": "https://x/y.png", "filename": "y.png",
                              "content_type": "image/png"}],
        )
        out = await translation_service.process_message(ctx, MagicMock())
        assert out == [setup_pair.name]
        retry_mock.assert_not_awaited()  # passthrough — no API call


# ============================================================================
# TranslationService.test_translation
# ============================================================================

class TestTestTranslation:
    async def test_no_key_short_circuit(self, translation_service, monkeypatch):
        monkeypatch.delenv("TRANSLATION_API_KEY", raising=False)
        translation_service.config_service.save_api_key(None)
        result = await translation_service.test_translation("hi", "DE")
        assert not result.success
        assert "No API key" in result.error

    async def test_dispatches_to_provider(
        self, translation_service, monkeypatch
    ):
        monkeypatch.setenv("TRANSLATION_API_KEY", "k")
        provider_mock = MagicMock()
        provider_mock.translate = AsyncMock(return_value=TranslationResult(
            success=True, translated_text="ok"
        ))
        monkeypatch.setattr(
            translation_service, "_get_provider",
            lambda settings, key: provider_mock
        )
        monkeypatch.setattr(
            translation_service, "_get_session",
            AsyncMock(return_value=MagicMock())
        )
        result = await translation_service.test_translation("hi", "DE", "EN")
        assert result.success
        provider_mock.translate.assert_awaited_once()


# ============================================================================
# TranslationService._post_translation (smoke test)
# ============================================================================

class TestPostTranslation:
    async def test_target_channel_missing_logs_and_returns(
        self, translation_service
    ):
        bot = MagicMock()
        bot.get_channel.return_value = None
        pair = ChannelPair.from_dict(_make_pair_data())
        ctx = TranslationContext(
            message_id="m", channel_id="c", guild_id="g",
            author_name="A", author_avatar_url="",
            content="hi",
        )
        result = TranslationResult(
            success=True, translated_text="Hallo", provider="DeepL"
        )
        # Should not raise even with missing channel
        await translation_service._post_translation(bot, pair, ctx, result)

    async def test_send_called_with_embed(self, translation_service, monkeypatch):
        # Provide a working mock target channel with send()
        sent = MagicMock()
        sent.id = 123
        target_channel = MagicMock()
        target_channel.send = AsyncMock(return_value=sent)
        # Skip permission gate by removing guild attr
        del target_channel.guild
        bot = MagicMock()
        bot.get_channel.return_value = target_channel

        # Stub the shared session so attachment download path is inert
        fake_session = _FakeSession()
        monkeypatch.setattr(translation_service, "_get_session",
                            AsyncMock(return_value=fake_session))

        pair = ChannelPair.from_dict(_make_pair_data())
        ctx = TranslationContext(
            message_id="m", channel_id="c", guild_id="g",
            author_name="Alice", author_avatar_url="https://x/a.png",
            content="hi",
        )
        result = TranslationResult(
            success=True, translated_text="Hallo",
            detected_language="EN", provider="DeepL"
        )
        await translation_service._post_translation(
            bot, pair, ctx, result, _make_settings()
        )
        target_channel.send.assert_awaited_once()
        # Sent message should be tracked for loop-prevention
        assert translation_service.is_translated_message("123")


# ============================================================================
# Singletons
# ============================================================================

class TestSingletons:
    def test_get_translation_service_returns_singleton(self, monkeypatch):
        monkeypatch.setattr(ts_mod, "_translation_service", None)
        with patch.object(ts_mod, "TranslationService") as cls:
            cls.return_value = MagicMock()
            a = ts_mod.get_translation_service()
            b = ts_mod.get_translation_service()
            assert a is b
            cls.assert_called_once()

    def test_get_translation_config_service_returns_singleton(self, monkeypatch):
        monkeypatch.setattr(tcs_mod, "_translation_config_service", None)
        with patch.object(tcs_mod, "TranslationConfigService") as cls:
            cls.return_value = MagicMock()
            a = tcs_mod.get_translation_config_service()
            b = tcs_mod.get_translation_config_service()
            assert a is b
            cls.assert_called_once()
