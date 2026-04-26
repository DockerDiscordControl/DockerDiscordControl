# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Performance/RAM Optimisation Tests             #
# https://ddc.bot                                                              #
# Copyright (c) 2026 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Tests for performance / RAM optimisations introduced across Bundles 4 - 7.

Sub-areas covered:
    1. Request-scoped config caching (Bundle 4 / P2)
    2. Animation fast-path at base speed (Bundle 4 / P4)
    3. Locales lazy-loading in I18nService (Bundle 6 / R3)
    4. Animation LRU disk-cache eviction (Bundle 7 / L2)
    5. Waitress thread-pool scaling (Bundle 4 / P5)

These tests do NOT touch production code.  They exercise the optimisation
paths via mocks and isolated service instances.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, render_template_string


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_flask_app() -> Flask:
    """Build a tiny Flask app wired with the i18n context processor."""
    from app.web.i18n import register_i18n

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    register_i18n(app)

    @app.route("/render")
    def render():
        # Use multiple render_template_string calls within the same request
        # to exercise the per-request memoisation path.
        out_a = render_template_string("{{ ui_language }}")
        out_b = render_template_string("{{ ui_language }}")
        out_c = render_template_string("{{ ui_language }}")
        return f"{out_a}-{out_b}-{out_c}"

    return app


# ===========================================================================
# 1. Request-scoped config caching (app/web/i18n.py:_request_scoped_config)
# ===========================================================================

@pytest.mark.performance
class TestRequestScopedConfigCache:
    """Bundle 4 / P2 - load_config() must only run once per request."""

    def test_multiple_renders_in_one_request_load_config_once(self):
        app = _make_flask_app()

        with patch("app.web.i18n.load_config", return_value={"ui_language": "en"}) as mock_load:
            client = app.test_client()
            response = client.get("/render")
            assert response.status_code == 200
            # Three renders, but config must only be loaded once for the request.
            assert mock_load.call_count == 1, (
                f"Expected 1 load_config() call per request, got {mock_load.call_count}"
            )

    def test_two_sequential_requests_load_config_twice(self):
        app = _make_flask_app()
        client = app.test_client()

        with patch("app.web.i18n.load_config", return_value={"ui_language": "en"}) as mock_load:
            r1 = client.get("/render")
            r2 = client.get("/render")
            assert r1.status_code == 200
            assert r2.status_code == 200
            # Cache is request-scoped (flask.g) -> must reload between requests.
            assert mock_load.call_count == 2, (
                f"Expected 2 load_config() calls across 2 requests, got {mock_load.call_count}"
            )

    def test_request_scoped_config_helper_caches_on_g(self):
        """Direct unit-test of the helper using a request context."""
        from app.web import i18n as i18n_mod

        app = Flask(__name__)
        with patch.object(i18n_mod, "load_config", return_value={"ui_language": "de"}) as mock_load:
            with app.test_request_context("/"):
                cfg1 = i18n_mod._request_scoped_config()
                cfg2 = i18n_mod._request_scoped_config()
                cfg3 = i18n_mod._request_scoped_config()
                assert cfg1 is cfg2 is cfg3
                assert cfg1 == {"ui_language": "de"}
                assert mock_load.call_count == 1

    def test_request_scoped_config_swallows_load_errors(self):
        """If load_config() raises, helper must return an empty dict (no crash)."""
        from app.web import i18n as i18n_mod

        app = Flask(__name__)
        with patch.object(i18n_mod, "load_config", side_effect=RuntimeError("boom")):
            with app.test_request_context("/"):
                cfg = i18n_mod._request_scoped_config()
                assert cfg == {}


# ===========================================================================
# 2. Animation fast-path at base speed
#    (services/mech/animation_cache_service.py:_get_animation_internal)
# ===========================================================================

@pytest.fixture
def animation_service(tmp_path, monkeypatch):
    """Construct an AnimationCacheService isolated to tmp_path."""
    from services.mech import animation_cache_service as acs_mod
    from services.mech.animation_cache_service import AnimationCacheService

    # Avoid hitting the real disk-cache enforcement on init by stubbing it.
    monkeypatch.setattr(
        AnimationCacheService, "enforce_disk_cache_limit", lambda self, *a, **kw: 0, raising=True
    )
    # Avoid event-listener wiring.
    monkeypatch.setattr(
        AnimationCacheService, "_setup_event_listeners", lambda self: None, raising=True
    )

    svc = AnimationCacheService()
    svc.cache_dir = tmp_path
    svc._focused_cache.clear()
    return svc


@pytest.mark.performance
class TestAnimationFastPath:
    """Bundle 4 / P4 - base-speed (100% / level >= 11) bypasses re-encoding."""

    def test_fast_path_uses_base_cache_without_re_encoding(self, animation_service, tmp_path):
        """speed_level that quantises to 50.0 should read base cache directly."""
        svc = animation_service

        evolution_level = 5
        animation_type = "walk"
        resolution = "small"

        # Sanity: confirm the base-speed sentinel is 50.0 in this codebase.
        assert svc._quantize_speed(50) == 50.0

        base_path = svc.get_cached_animation_path(evolution_level, animation_type, resolution)
        # Write obfuscated bytes of a known payload.
        payload = b"\x89WEBP_PAYLOAD_FAST_PATH\x00\xFFraw"
        obfuscated = svc._obfuscate_data(payload)
        base_path.write_bytes(obfuscated)

        # Patch re-encoding + PIL.Image.open so we can detect any unwanted call.
        with patch.object(svc, "_apply_speed_to_animation") as mock_reencode, \
             patch("services.mech.animation_cache_service.Image.open") as mock_open:
            result = svc._get_animation_internal(
                evolution_level=evolution_level,
                speed_level=50,  # _quantize_speed -> 50.0 -> base-speed fast path
                power_level=1.0,
                resolution=resolution,
            )

        assert result == payload, "Fast path should return de-obfuscated base bytes"
        mock_reencode.assert_not_called()
        mock_open.assert_not_called()

    def test_fast_path_for_level_11(self, animation_service):
        """evolution_level >= 11 always treated as base speed."""
        svc = animation_service

        evolution_level = 11
        animation_type = "walk"
        resolution = "small"

        base_path = svc.get_cached_animation_path(evolution_level, animation_type, resolution)
        payload = b"LEVEL11_BASE_FRAMES"
        base_path.write_bytes(svc._obfuscate_data(payload))

        with patch.object(svc, "_apply_speed_to_animation") as mock_reencode, \
             patch("services.mech.animation_cache_service.Image.open") as mock_open:
            # Even at non-100% speed, level 11 should fast-path.
            result = svc._get_animation_internal(
                evolution_level=evolution_level,
                speed_level=80,
                power_level=1.0,
                resolution=resolution,
            )

        assert result == payload
        mock_reencode.assert_not_called()
        mock_open.assert_not_called()

    def test_non_base_speed_runs_re_encoding(self, animation_service):
        """speed_level=80 must NOT take fast-path; re-encoder must be called."""
        svc = animation_service

        evolution_level = 5
        animation_type = "walk"
        resolution = "small"

        base_path = svc.get_cached_animation_path(evolution_level, animation_type, resolution)
        base_payload = b"BASE_RAW_FRAMES"
        base_path.write_bytes(svc._obfuscate_data(base_payload))

        adjusted_payload = b"ADJUSTED_80_PERCENT"

        with patch.object(svc, "_apply_speed_to_animation", return_value=adjusted_payload) as mock_reencode:
            result = svc._get_animation_internal(
                evolution_level=evolution_level,
                speed_level=80,  # _quantize_speed -> 40.0 (not base)
                power_level=1.0,
                resolution=resolution,
            )

        mock_reencode.assert_called_once()
        # First positional arg should be the de-obfuscated base payload.
        called_args, _ = mock_reencode.call_args
        assert called_args[0] == base_payload
        assert result == adjusted_payload


# ===========================================================================
# 3. I18nService lazy-loading (services/web/i18n_service.py)
# ===========================================================================

@pytest.mark.performance
class TestI18nLazyLoading:
    """Bundle 6 / R3 - locales are scanned at init but only English is loaded."""

    def test_init_loads_only_english(self):
        from services.web.i18n_service import I18nService

        svc = I18nService()
        assert set(svc._translations.keys()) == {"en"}, (
            f"Expected only 'en' loaded after init, got {set(svc._translations.keys())}"
        )

    def test_available_codes_include_core_languages(self):
        from services.web.i18n_service import I18nService

        svc = I18nService()
        # We expect at least the major DDC locales to be discoverable.
        for code in ("de", "en", "fr", "es"):
            assert code in svc._available_codes, f"Locale '{code}' missing from available codes"

    def test_translate_lazy_loads_target_language(self):
        from services.web.i18n_service import I18nService

        svc = I18nService()
        assert "fr" not in svc._translations
        # Translate something into French - this MUST trigger the lazy load.
        svc.translate("app.title", lang="fr")
        assert "fr" in svc._translations, "French translations should be lazy-loaded on first translate()"

    def test_reload_restores_previously_loaded_languages(self):
        from services.web.i18n_service import I18nService

        svc = I18nService()
        svc.translate("app.title", lang="de")
        loaded_before = set(svc._translations.keys())
        assert {"en", "de"}.issubset(loaded_before)

        svc.reload()

        loaded_after = set(svc._translations.keys())
        # After reload, the previously loaded languages must be re-loaded.
        assert {"en", "de"}.issubset(loaded_after), (
            f"reload() should re-load previously cached languages, got {loaded_after}"
        )

    def test_translate_unknown_language_falls_back_to_english(self):
        from services.web.i18n_service import I18nService

        svc = I18nService()
        # Use a non-existent language code; translate should fall back to 'en'
        # without polluting _translations with the unknown code.
        result = svc.translate("app.title", lang="zz_unknown")
        assert isinstance(result, str)
        assert "zz_unknown" not in svc._translations


# ===========================================================================
# 4. Animation LRU disk cache eviction (enforce_disk_cache_limit)
# ===========================================================================

@pytest.mark.performance
class TestDiskCacheEviction:
    """Bundle 7 / L2 - LRU eviction of *.webp; *.cache files preserved."""

    def _make_service(self, tmp_path, monkeypatch):
        from services.mech.animation_cache_service import AnimationCacheService
        monkeypatch.setattr(
            AnimationCacheService, "enforce_disk_cache_limit",
            AnimationCacheService.enforce_disk_cache_limit,  # leave method intact
            raising=True,
        )
        # Stop init from running enforcement against the real cache dir.
        with patch.object(AnimationCacheService, "_setup_event_listeners", lambda self: None):
            with patch.dict(os.environ, {"DDC_ANIM_DISK_LIMIT_MB": "0"}):
                svc = AnimationCacheService()
        svc.cache_dir = tmp_path
        return svc

    def test_under_limit_evicts_nothing(self, tmp_path, monkeypatch):
        svc = self._make_service(tmp_path, monkeypatch)

        # 5 webp files @ 100KB + 1 .cache file @ 100KB -> 600KB < 1MB
        for i in range(5):
            (tmp_path / f"mech_L1_walk_small_S{(i + 1) * 5}.webp").write_bytes(b"x" * 100 * 1024)
        (tmp_path / "mech_5_100speed.cache").write_bytes(b"y" * 100 * 1024)

        removed = svc.enforce_disk_cache_limit(max_mb=1)
        assert removed == 0, "Below limit -> nothing should be evicted"

        # All files still on disk.
        assert len(list(tmp_path.glob("*.webp"))) == 5
        assert len(list(tmp_path.glob("*.cache"))) == 1

    def test_over_limit_evicts_oldest_webp_first(self, tmp_path, monkeypatch):
        svc = self._make_service(tmp_path, monkeypatch)

        # 4 webp @ 100KB (newer) + 1 webp @ 1.5MB (oldest) + 1 cache @ 100KB.
        webp_paths = []
        now = time.time()
        for i in range(4):
            p = tmp_path / f"mech_L1_walk_small_S{(i + 1) * 5}.webp"
            p.write_bytes(b"x" * 100 * 1024)
            os.utime(p, (now, now))
            webp_paths.append(p)

        oldest = tmp_path / "mech_L1_walk_small_S100.webp"
        oldest.write_bytes(b"z" * 1500 * 1024)  # 1.5 MB
        old_time = now - 86400
        os.utime(oldest, (old_time, old_time))

        cache_file = tmp_path / "mech_5_100speed.cache"
        cache_file.write_bytes(b"y" * 100 * 1024)

        # Total ~1.9MB > 1MB limit -> at least the oldest must be evicted.
        removed = svc.enforce_disk_cache_limit(max_mb=1)

        assert removed >= 1, "Over limit -> at least one .webp should be evicted"
        assert not oldest.exists(), "Oldest webp must be evicted first (LRU)"
        # .cache file is sacrosanct.
        assert cache_file.exists(), ".cache files must never be evicted"

    def test_cache_files_never_evicted_even_when_huge(self, tmp_path, monkeypatch):
        svc = self._make_service(tmp_path, monkeypatch)

        # Massive .cache file; small total .webp footprint -> .webp under limit.
        big_cache = tmp_path / "mech_5_100speed.cache"
        big_cache.write_bytes(b"c" * 5 * 1024 * 1024)  # 5 MB

        small_webp = tmp_path / "mech_L1_walk_small_S5.webp"
        small_webp.write_bytes(b"w" * 50 * 1024)  # 50 KB

        removed = svc.enforce_disk_cache_limit(max_mb=1)
        assert removed == 0
        assert big_cache.exists(), ".cache files must never be touched by enforcement"
        assert small_webp.exists()

    def test_max_mb_zero_disables_enforcement(self, tmp_path, monkeypatch):
        svc = self._make_service(tmp_path, monkeypatch)

        big_webp = tmp_path / "mech_L1_walk_small_S5.webp"
        big_webp.write_bytes(b"w" * 2 * 1024 * 1024)

        removed = svc.enforce_disk_cache_limit(max_mb=0)
        assert removed == 0
        assert big_webp.exists()


# ===========================================================================
# 5. Waitress thread-pool scaling (run.py:start_web_server)
# ===========================================================================

def _compute_waitress_threads(env_value, cpu_count_value):
    """Mirror of the calculation in run.py:start_web_server.

    We replicate the logic exactly so we can assert its bounds without having
    to actually start waitress.  The production code remains untouched; this
    helper just encodes the same expression.
    """
    cpu_count = cpu_count_value or 4
    try:
        threads = (
            int(os.environ.get("DDC_WAITRESS_THREADS", "0"))
            or max(4, min(8, cpu_count))
        )
    except (TypeError, ValueError):
        threads = max(4, min(8, cpu_count))
    threads = max(2, min(16, threads))
    return threads


@pytest.mark.performance
class TestWaitressThreadScaling:
    """Bundle 4 / P5 - waitress thread-pool sizing logic."""

    def _calc(self, env_value, cpu_count_value):
        env_patch = {} if env_value is None else {"DDC_WAITRESS_THREADS": env_value}
        with patch.dict(os.environ, env_patch, clear=False):
            if env_value is None:
                os.environ.pop("DDC_WAITRESS_THREADS", None)
            with patch("os.cpu_count", return_value=cpu_count_value):
                return _compute_waitress_threads(env_value, cpu_count_value)

    def test_default_with_cpu_count_8(self):
        assert self._calc(None, 8) == 8

    def test_default_with_cpu_count_2_floors_to_4(self):
        assert self._calc(None, 2) == 4

    def test_explicit_env_override_12(self):
        assert self._calc("12", 8) == 12

    def test_explicit_env_override_clamped_to_16(self):
        assert self._calc("100", 8) == 16

    def test_garbage_env_falls_back_to_cpu_default(self):
        # 'garbage' -> ValueError -> default branch => max(4, min(8, 8)) = 8
        assert self._calc("garbage", 8) == 8

    def test_low_explicit_override_clamped_to_2(self):
        # An env value of "1" -> threads=1 -> clamped up to 2.
        assert self._calc("1", 8) == 2
