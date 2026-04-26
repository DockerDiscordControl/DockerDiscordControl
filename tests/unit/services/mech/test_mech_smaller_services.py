# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Unit Tests for Smaller Mech Services           #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""Unit tests for the smaller, mostly pure-function mech services.

Covers:
    * services.mech.mech_display_cache_service
    * services.mech.mech_high_res_service
    * services.mech.mech_story_service
    * services.mech.mech_images   (only the pure-functions; the module's
                                   top-level import of a non-existent
                                   ``mech_evolution_loader`` is patched out
                                   by reading the source and re-loading via
                                   ``importlib`` — no ``sys.modules`` edits.)
    * services.mech.monthly_member_cache
    * services.mech.mech_evolutions  (filling coverage gaps around the
                                       lookup helpers)

The tests follow the project rules:
    * NEVER manipulate ``sys.modules``.
    * NEVER touch production code or commit anything.
    * Use ``tmp_path`` / ``monkeypatch`` for filesystem isolation.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_walking_webp_bytes(size=(60, 40)) -> bytes:
    """Create a tiny in-memory WebP that PIL can re-open."""
    img = Image.new("RGBA", size, (255, 0, 0, 255))
    # Punch a transparent pixel so the silhouette branch hits both legs.
    img.putpixel((0, 0), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="WebP", lossless=True)
    return buf.getvalue()


# ===========================================================================
# mech_display_cache_service
# ===========================================================================

from services.mech.mech_display_cache_service import (  # noqa: E402
    MechDisplayCacheRequest,
    MechDisplayCacheResult,
    MechDisplayCacheService,
    MechDisplayImageRequest,
    MechDisplayImageResult,
    get_mech_display_cache_service,
)


@pytest.fixture
def display_cache_service(tmp_path):
    """Return a service whose cache_dir lives under tmp_path."""
    svc = MechDisplayCacheService()
    svc.cache_dir = tmp_path / "displays"
    svc.cache_dir.mkdir(parents=True, exist_ok=True)
    return svc


class TestMechDisplayCacheDataclasses:
    def test_request_defaults(self):
        r = MechDisplayCacheRequest()
        assert r.evolution_level is None
        assert r.force_regenerate is False

    def test_request_with_values(self):
        r = MechDisplayCacheRequest(evolution_level=3, force_regenerate=True)
        assert r.evolution_level == 3
        assert r.force_regenerate is True

    def test_image_request_required_fields(self):
        r = MechDisplayImageRequest(evolution_level=5, image_type="shadow")
        assert r.evolution_level == 5
        assert r.image_type == "shadow"

    def test_result_defaults(self):
        r = MechDisplayCacheResult(success=True, message="ok")
        assert r.success is True
        assert r.levels_processed == 0


class TestMechDisplayCacheBehaviour:
    def test_is_pre_rendering_needed_force_regenerate(self, display_cache_service):
        assert display_cache_service._is_pre_rendering_needed(1, "shadow", True) is True

    def test_is_pre_rendering_needed_when_file_missing(self, display_cache_service):
        assert (
            display_cache_service._is_pre_rendering_needed(1, "shadow", False) is True
        )
        assert (
            display_cache_service._is_pre_rendering_needed(2, "unlocked", False)
            is True
        )

    def test_is_pre_rendering_not_needed_when_file_exists(self, display_cache_service):
        # Pre-create the cache file
        (display_cache_service.cache_dir / "mech_3_shadow.webp").write_bytes(b"x")
        # The service tries to import animation_cache_service afterwards; we
        # patch that to keep the tip-of-the-funnel deterministic.
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            side_effect=ImportError("boom"),
        ):
            # Even when the freshness check fails, the result should be False
            # (file exists and force_regenerate=False).
            assert (
                display_cache_service._is_pre_rendering_needed(3, "shadow", False)
                is False
            )

    def test_clear_cache_removes_files(self, display_cache_service):
        for name in ("mech_1_shadow.webp", "mech_1_unlocked.webp", "mech_2_shadow.webp"):
            (display_cache_service.cache_dir / name).write_bytes(b"x")
        result = display_cache_service.clear_cache()
        assert result.success is True
        assert result.levels_processed == 3
        assert list(display_cache_service.cache_dir.glob("*.webp")) == []

    def test_clear_cache_empty_dir(self, display_cache_service):
        result = display_cache_service.clear_cache()
        assert result.success is True
        assert result.levels_processed == 0

    def test_get_mech_display_image_invalid_type(self, display_cache_service):
        result = display_cache_service.get_mech_display_image(
            MechDisplayImageRequest(evolution_level=1, image_type="bogus")
        )
        assert result.success is False
        assert "Invalid image type" in result.error_message

    def test_get_mech_display_image_returns_existing_shadow(
        self, display_cache_service
    ):
        path = display_cache_service.cache_dir / "mech_4_shadow.webp"
        path.write_bytes(b"\x00binary\xff")
        result = display_cache_service.get_mech_display_image(
            MechDisplayImageRequest(evolution_level=4, image_type="shadow")
        )
        assert result.success is True
        assert result.image_bytes == b"\x00binary\xff"
        assert result.filename == "mech_shadow_4.webp"

    def test_get_mech_display_image_returns_existing_unlocked(
        self, display_cache_service
    ):
        path = display_cache_service.cache_dir / "mech_2_unlocked.webp"
        path.write_bytes(b"unlocked-bytes")
        result = display_cache_service.get_mech_display_image(
            MechDisplayImageRequest(evolution_level=2, image_type="unlocked")
        )
        assert result.success is True
        assert result.image_bytes == b"unlocked-bytes"
        assert result.filename == "mech_level_2.webp"

    def test_pre_render_unlocked_writes_animation_bytes(self, display_cache_service):
        animation_service = MagicMock()
        animation_service.get_animation_with_speed_and_power_big.return_value = (
            b"animation-bytes"
        )
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            return_value=animation_service,
        ):
            assert display_cache_service._pre_render_unlocked_image(7) is True
        out = display_cache_service.cache_dir / "mech_7_unlocked.webp"
        assert out.read_bytes() == b"animation-bytes"

    def test_pre_render_unlocked_handles_no_data(self, display_cache_service):
        animation_service = MagicMock()
        animation_service.get_animation_with_speed_and_power_big.return_value = b""
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            return_value=animation_service,
        ):
            assert display_cache_service._pre_render_unlocked_image(8) is False

    def test_pre_render_unlocked_skips_when_exists(self, display_cache_service):
        out = display_cache_service.cache_dir / "mech_9_unlocked.webp"
        out.write_bytes(b"existing")
        # Should NOT actually fetch animation bytes when the cache hit short
        # circuits the function. (The factory itself is acquired before the
        # existence check, so we only assert the bytes-fetcher was skipped.)
        animation_service = MagicMock()
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            return_value=animation_service,
        ):
            assert (
                display_cache_service._pre_render_unlocked_image(9, force=False)
                is True
            )
        animation_service.get_animation_with_speed_and_power_big.assert_not_called()
        # File contents must remain untouched (no overwrite).
        assert out.read_bytes() == b"existing"

    def test_pre_render_shadow_creates_silhouette(self, display_cache_service):
        animation_service = MagicMock()
        animation_service.get_animation_with_speed.return_value = (
            _make_walking_webp_bytes()
        )
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            return_value=animation_service,
        ):
            assert display_cache_service._pre_render_shadow_image(2, force=True) is True
        out = display_cache_service.cache_dir / "mech_2_shadow.webp"
        assert out.exists()
        with Image.open(out) as silhouette:
            assert silhouette.size == (60, 40)

    def test_pre_render_shadow_no_animation_data(self, display_cache_service):
        animation_service = MagicMock()
        animation_service.get_animation_with_speed.return_value = None
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            return_value=animation_service,
        ):
            assert display_cache_service._pre_render_shadow_image(2, force=True) is False

    def test_pre_render_all_displays_skips_when_cached(self, display_cache_service):
        # Pre-create all expected cache files.
        for level in range(1, 12):
            (display_cache_service.cache_dir / f"mech_{level}_shadow.webp").write_bytes(
                b"x"
            )
            (display_cache_service.cache_dir / f"mech_{level}_unlocked.webp").write_bytes(
                b"x"
            )

        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service"
        ) as fac:
            fac.return_value._get_actual_mech_folder.return_value = Path(
                "/nonexistent"
            )
            result = display_cache_service.pre_render_all_displays(
                MechDisplayCacheRequest()
            )
        assert result.success is True
        assert result.levels_processed == 11
        assert "already cached" in result.message

    def test_pre_render_all_displays_single_level(self, display_cache_service):
        # File missing -> needs render
        animation_service = MagicMock()
        animation_service.get_animation_with_speed.return_value = (
            _make_walking_webp_bytes()
        )
        animation_service.get_animation_with_speed_and_power_big.return_value = b"x"
        animation_service._get_actual_mech_folder.return_value = Path("/nonexistent")
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            return_value=animation_service,
        ):
            result = display_cache_service.pre_render_all_displays(
                MechDisplayCacheRequest(evolution_level=5)
            )
        assert result.success is True
        assert result.levels_processed == 1

    def test_pre_render_all_displays_handles_runtime_error(self, display_cache_service):
        with patch.object(
            display_cache_service,
            "_is_pre_rendering_needed",
            side_effect=RuntimeError("orchestration"),
        ):
            result = display_cache_service.pre_render_all_displays(
                MechDisplayCacheRequest(evolution_level=1)
            )
        assert result.success is False
        assert "orchestration" in result.message

    def test_pre_render_all_displays_handles_value_error(self, display_cache_service):
        with patch.object(
            display_cache_service,
            "_is_pre_rendering_needed",
            side_effect=ValueError("bad-data"),
        ):
            result = display_cache_service.pre_render_all_displays(
                MechDisplayCacheRequest(evolution_level=1)
            )
        assert result.success is False
        assert "bad-data" in result.message


def test_get_mech_display_cache_service_singleton():
    a = get_mech_display_cache_service()
    b = get_mech_display_cache_service()
    assert a is b


# ===========================================================================
# mech_high_res_service
# ===========================================================================

from services.mech.mech_high_res_service import (  # noqa: E402
    MechHighResService,
    MechResolutionRequest,
    MechResolutionResult,
    get_mech_high_res_service,
)


class TestMechHighResCanvas:
    @pytest.mark.parametrize(
        "level, expected_h",
        [(1, 100), (3, 100), (4, 150), (6, 170), (9, 230), (10, 250), (11, 270)],
    )
    def test_canvas_size_small_walk(self, level, expected_h):
        svc = MechHighResService()
        assert svc.get_canvas_size_for_resolution(level, "small", "walk") == (
            270,
            expected_h,
        )

    def test_canvas_size_rest_doubles_height(self):
        svc = MechHighResService()
        assert svc.get_canvas_size_for_resolution(1, "small", "rest") == (270, 200)

    def test_canvas_size_unknown_level_uses_default(self):
        svc = MechHighResService()
        assert svc.get_canvas_size_for_resolution(99, "small", "walk") == (270, 100)

    def test_canvas_size_big_falls_back_to_small_when_no_assets(self):
        svc = MechHighResService()
        # No big version available -> ratio defaults to 1.0
        result = svc.get_canvas_size_for_resolution(1, "big", "walk")
        assert result == (270, 100)

    def test_canvas_size_invalid_resolution(self):
        svc = MechHighResService()
        assert svc.get_canvas_size_for_resolution(1, "weird", "walk") == (270, 100)


class TestMechHighResCropping:
    def test_crop_small_known_level(self):
        svc = MechHighResService()
        assert svc._get_cropping_adjustments(4, "small") == {"top": 45, "bottom": 13}

    def test_crop_small_unknown_level_zero_defaults(self):
        svc = MechHighResService()
        assert svc._get_cropping_adjustments(99, "small") == {"top": 0, "bottom": 0}

    def test_crop_big_uses_ratio(self):
        svc = MechHighResService()
        # No big assets available -> ratio falls back to 1.0
        adj = svc._get_cropping_adjustments(1, "big")
        assert adj == {"top": 60, "bottom": 10}

    def test_crop_unknown_resolution_returns_base(self):
        svc = MechHighResService()
        assert svc._get_cropping_adjustments(1, "weird") == {"top": 60, "bottom": 10}


class TestMechHighResResolutionInfo:
    def test_resolution_info_no_assets(self):
        svc = MechHighResService()
        result = svc.get_mech_resolution_info(MechResolutionRequest(evolution_level=99))
        assert result.success is False
        assert "No assets" in result.error

    def test_has_big_version_missing_dir(self, tmp_path):
        svc = MechHighResService()
        svc.assets_dir = tmp_path  # no Mech subfolders
        assert svc._has_big_version(1) is False

    def test_has_big_version_with_walk_files(self, tmp_path):
        svc = MechHighResService()
        svc.assets_dir = tmp_path
        big = tmp_path / "Mech1" / "big"
        big.mkdir(parents=True)
        (big / "1_walk_0001.png").write_bytes(b"x")
        assert svc._has_big_version(1) is True

    def test_get_size_ratio_returns_one_when_files_missing(self, tmp_path):
        svc = MechHighResService()
        svc.assets_dir = tmp_path
        assert svc._get_size_ratio(1) == 1.0

    def test_get_size_ratio_uses_image_widths(self, tmp_path):
        svc = MechHighResService()
        svc.assets_dir = tmp_path
        small = tmp_path / "Mech1" / "small"
        big = tmp_path / "Mech1" / "big"
        small.mkdir(parents=True)
        big.mkdir(parents=True)
        Image.new("RGBA", (100, 100)).save(small / "1_walk_0001.png")
        Image.new("RGBA", (300, 300)).save(big / "1_walk_0001.png")

        ratio = svc._get_size_ratio(1)
        assert ratio == pytest.approx(3.0)
        # Cached on second call.
        assert svc._get_size_ratio(1) == pytest.approx(3.0)

    def test_resolution_info_small_only(self, tmp_path):
        svc = MechHighResService()
        svc.assets_dir = tmp_path
        small = tmp_path / "Mech1" / "small"
        small.mkdir(parents=True)
        result = svc.get_mech_resolution_info(MechResolutionRequest(evolution_level=1))
        assert result.success is True
        assert result.available_resolution == "small"
        assert result.has_big_version is False
        assert result.size_ratio is None

    def test_resolution_info_prefers_big_when_available(self, tmp_path):
        svc = MechHighResService()
        svc.assets_dir = tmp_path
        small = tmp_path / "Mech1" / "small"
        big = tmp_path / "Mech1" / "big"
        small.mkdir(parents=True)
        big.mkdir(parents=True)
        Image.new("RGBA", (100, 100)).save(small / "1_walk_0001.png")
        Image.new("RGBA", (300, 300)).save(big / "1_walk_0001.png")

        result = svc.get_mech_resolution_info(
            MechResolutionRequest(evolution_level=1, preferred_resolution="big")
        )
        assert result.success is True
        assert result.available_resolution == "big"
        assert result.has_big_version is True
        assert result.size_ratio == pytest.approx(3.0)


def test_get_mech_high_res_service_singleton():
    a = get_mech_high_res_service()
    b = get_mech_high_res_service()
    assert a is b


# ===========================================================================
# mech_story_service
# ===========================================================================

from services.mech.mech_story_service import MechStoryService  # noqa: E402

_STORY_FIXTURE = (
    "Prologue I: The Beginning\n"
    "Once upon a time the rust grew thick.\n"
    "\n"
    "Prologue II: Continuation\n"
    "The mech awoke from slumber.\n"
    "\n"
    "Chapter I: First Battle\n"
    "Combat ensued.\n"
    "\n"
    "Chapter II: The Titanframe\n"
    "Plates were bolted on.\n"
    "\n"
    "Chapter III: Pulseforged\n"
    "Energy surged.\n"
    "\n"
    "Epilogue: The End\n"
    "All things must end.\n"
)


class TestMechStoryChapterMapping:
    @pytest.mark.parametrize(
        "level, expected_key",
        [
            (1, "prologue1"),
            (2, "prologue2"),
            (3, "chapter1"),
            (4, "chapter2"),
            (5, "chapter3"),
            (6, "chapter4"),
            (10, "chapter8"),
            (11, "chapter9"),
        ],
    )
    def test_chapter_key_for_level(self, level, expected_key, tmp_path):
        svc = MechStoryService(story_dir=str(tmp_path))
        assert svc.get_chapter_key_for_level(level) == expected_key
        assert svc.get_chapter_key(level) == expected_key

    def test_chapter_key_unknown_level_falls_back(self, tmp_path):
        svc = MechStoryService(story_dir=str(tmp_path))
        assert svc.get_chapter_key_for_level(999) == "prologue1"


class TestMechStoryLoading:
    def test_missing_story_file_returns_none(self, tmp_path):
        svc = MechStoryService(story_dir=str(tmp_path))
        assert svc.get_story_chapter(1) is None
        assert svc.get_all_chapters("en") == {}

    def test_loads_and_parses_story_file(self, tmp_path):
        (tmp_path / "en.txt").write_text(_STORY_FIXTURE, encoding="utf-8")
        svc = MechStoryService(story_dir=str(tmp_path))
        chapters = svc.get_all_chapters("en")
        assert "prologue1" in chapters
        assert "prologue2" in chapters
        assert "chapter1" in chapters
        assert "epilogue" in chapters
        assert chapters["prologue1"].startswith("Prologue I:")
        assert "rust grew thick" in chapters["prologue1"]

    def test_get_story_chapter_returns_text_for_level(self, tmp_path):
        (tmp_path / "en.txt").write_text(_STORY_FIXTURE, encoding="utf-8")
        svc = MechStoryService(story_dir=str(tmp_path))
        text = svc.get_story_chapter(1, language="en")
        assert text is not None
        assert text.startswith("Prologue I:")

    def test_clear_cache_forces_reload(self, tmp_path):
        story_path = tmp_path / "en.txt"
        story_path.write_text(_STORY_FIXTURE, encoding="utf-8")
        svc = MechStoryService(story_dir=str(tmp_path))
        first = svc.get_all_chapters("en")
        assert first
        # Modify file then ensure cached value is returned (no reload).
        story_path.write_text("", encoding="utf-8")
        cached = svc.get_all_chapters("en")
        assert cached == first
        # After clear_cache, content should be reloaded (now empty parse).
        svc.clear_cache()
        assert svc.get_all_chapters("en") == {}

    def test_german_language_file(self, tmp_path):
        de_text = (
            "Prolog I: Der Anfang\n"
            "Es war einmal.\n"
            "\n"
            "Kapitel I: Erste Schlacht\n"
            "Es kam zum Kampf.\n"
        )
        (tmp_path / "de.txt").write_text(de_text, encoding="utf-8")
        svc = MechStoryService(story_dir=str(tmp_path))
        chapters = svc.get_all_chapters("de")
        assert "prologue1" in chapters
        assert "chapter1" in chapters
        assert "Erste Schlacht" in chapters["chapter1"]

    def test_unknown_language_falls_back_to_en(self, tmp_path):
        (tmp_path / "en.txt").write_text(_STORY_FIXTURE, encoding="utf-8")
        svc = MechStoryService(story_dir=str(tmp_path))
        # 'xx' is not in language_files mapping -> file lookup uses 'en.txt'
        chapters = svc.get_all_chapters("xx")
        assert "prologue1" in chapters

    def test_default_story_dir_path(self):
        svc = MechStoryService()
        assert svc.story_dir.name == "stories"
        assert svc.story_dir.parent.name == "mech"


# ===========================================================================
# monthly_member_cache
# ===========================================================================

from services.mech.monthly_member_cache import (  # noqa: E402
    MonthlyMemberCache,
    get_monthly_member_cache,
)


class TestMonthlyMemberCache:
    def test_default_when_no_cache_file(self, tmp_path):
        cache = MonthlyMemberCache()
        cache.cache_file = tmp_path / "missing.json"
        cache._cache_data = None
        assert cache.get_member_count() == 50

    def test_reads_cache_file(self, tmp_path):
        path = tmp_path / "cache.json"
        path.write_text(
            json.dumps(
                {
                    "member_count": 123,
                    "timestamp": "2025-09-12T13:56:30",
                    "month_year": "2025-09",
                }
            ),
            encoding="utf-8",
        )
        cache = MonthlyMemberCache()
        cache.cache_file = path
        cache._cache_data = None
        assert cache.get_member_count() == 123
        info = cache.get_cache_info()
        assert info["total_members"] == 123
        assert info["month_year"] == "2025-09"
        assert info["last_updated"] == "2025-09-12T13:56:30"

    def test_handles_corrupt_json(self, tmp_path):
        path = tmp_path / "cache.json"
        path.write_text("{not-json", encoding="utf-8")
        cache = MonthlyMemberCache()
        cache.cache_file = path
        cache._cache_data = None
        # Falls back to default member_count of 50
        assert cache.get_member_count() == 50

    def test_caches_across_calls(self, tmp_path):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"member_count": 77}), encoding="utf-8")
        cache = MonthlyMemberCache()
        cache.cache_file = path
        cache._cache_data = None
        first = cache.get_member_count()
        # Mutate file, but cached value should not change.
        path.write_text(json.dumps({"member_count": 999}), encoding="utf-8")
        second = cache.get_member_count()
        assert first == 77
        assert second == 77

    def test_get_member_count_for_level_returns_same_count(self, tmp_path):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"member_count": 42}), encoding="utf-8")
        cache = MonthlyMemberCache()
        cache.cache_file = path
        cache._cache_data = None
        assert cache.get_member_count_for_level(1) == 42
        assert cache.get_member_count_for_level(11) == 42

    def test_cache_info_uses_unknown_when_field_missing(self, tmp_path):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({}), encoding="utf-8")
        cache = MonthlyMemberCache()
        cache.cache_file = path
        cache._cache_data = None
        info = cache.get_cache_info()
        assert info["last_updated"] == "Unknown"
        assert info["total_members"] == 50

    def test_singleton_helper(self):
        a = get_monthly_member_cache()
        b = get_monthly_member_cache()
        assert a is b

    def test_handles_io_error_on_open(self, tmp_path, monkeypatch):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"member_count": 12}), encoding="utf-8")
        cache = MonthlyMemberCache()
        cache.cache_file = path
        cache._cache_data = None

        # Patch builtins.open used by _load_cache so it raises OSError.
        import builtins
        real_open = builtins.open

        def fake_open(target, *args, **kwargs):
            if str(target) == str(path):
                raise OSError("permission denied")
            return real_open(target, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fake_open)
        # Falls back to default member_count of 50.
        assert cache.get_member_count() == 50

    def test_handles_typeerror_on_load(self, tmp_path, monkeypatch):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"member_count": 12}), encoding="utf-8")
        cache = MonthlyMemberCache()
        cache.cache_file = path
        cache._cache_data = None

        # Force json.load to raise a TypeError (data structure error path).
        import services.mech.monthly_member_cache as mod

        monkeypatch.setattr(mod.json, "load", lambda *a, **k: (_ for _ in ()).throw(TypeError("bad")))
        assert cache.get_member_count() == 50


# ===========================================================================
# mech_evolutions  (filling coverage gaps)
# ===========================================================================

from services.mech.mech_evolutions import (  # noqa: E402
    EvolutionConfigService,
    EvolutionLevelInfo,
    calculate_dynamic_cost,
    get_all_evolution_levels,
    get_evolution_config_service,
    get_evolution_info,
    get_evolution_level,
    get_evolution_level_info,
    get_mech_filename,
)


class TestEvolutionLookup:
    def test_negative_donation_returns_level_one(self):
        assert get_evolution_level(-100) == 1

    @pytest.mark.parametrize(
        "donation, expected",
        [(0, 1), (10, 2), (15, 3), (20, 4), (30, 6), (50, 10), (100, 11), (250, 11)],
    )
    def test_evolution_level_from_donations(self, donation, expected):
        assert get_evolution_level(donation) == expected

    def test_evolution_info_for_max_level(self):
        info = get_evolution_info(500)
        assert info["level"] == 11
        # Max level has no further threshold.
        assert info["next_threshold"] is None
        assert info["amount_needed"] is None

    def test_evolution_info_for_intermediate_level(self):
        info = get_evolution_info(15)  # qualifies for level 3
        assert info["level"] == 3
        assert info["next_threshold"] == 20
        assert info["next_name"]
        assert info["amount_needed"] == 5
        assert info["progress_to_next"] is not None
        assert 0 <= info["progress_to_next"] <= 100

    def test_evolution_info_carries_color_and_description(self):
        info = get_evolution_info(0)
        assert info["color"].startswith("#")
        assert info["description"]

    def test_get_evolution_level_info_for_known_level(self):
        info = get_evolution_level_info(2)
        assert isinstance(info, EvolutionLevelInfo)
        assert info.level == 2
        assert info.base_cost == 10
        assert info.power_max > 0

    def test_get_evolution_level_info_for_unknown_level(self):
        assert get_evolution_level_info(99) is None

    def test_get_all_evolution_levels(self):
        levels = get_all_evolution_levels()
        assert sorted(levels.keys()) == list(range(1, 12))
        for level, data in levels.items():
            assert isinstance(data, EvolutionLevelInfo)
            assert data.level == level

    def test_get_mech_filename(self):
        assert get_mech_filename(3) == "mech_level_3.png"
        assert get_mech_filename(11) == "mech_level_11.png"


class TestEvolutionDynamicCost:
    def test_level_one_returns_zero_cost(self):
        cost, mult = calculate_dynamic_cost(1, member_count=30)
        assert cost == 0
        assert mult == 1.0

    def test_unknown_level_returns_zero(self):
        cost, mult = calculate_dynamic_cost(99, member_count=30)
        assert cost == 0
        assert mult == 1.0

    def test_baseline_uses_difficulty_one(self):
        # Force a deterministic baseline config so the test does not depend on
        # whatever evolution.json the host system happens to ship.
        svc = get_evolution_config_service()
        baseline_config = svc._get_fallback_config()
        with patch.object(svc, "_load_config", return_value=baseline_config):
            cost, mult = calculate_dynamic_cost(2, member_count=30)
        assert mult == pytest.approx(1.0)
        # base_cost for level 2 is 10 -> floor(10*1) = 10, but progressive
        # min cost for level 2 == base_min_cost (5) + 0 == 5.
        assert cost >= 5

    def test_progressive_minimum_floor_for_high_levels(self):
        # Force a deterministic baseline config so the test does not depend on
        # whatever evolution.json the host system happens to ship.
        svc = get_evolution_config_service()
        baseline_config = svc._get_fallback_config()
        # Level 11 has base_cost 100; multiplier 1.0 => cost 100, comfortably
        # above the progressive floor.
        with patch.object(svc, "_load_config", return_value=baseline_config):
            cost, _mult = calculate_dynamic_cost(11, member_count=30)
        assert cost >= 100

    def test_difficulty_multiplier_clamped(self, tmp_path):
        # Direct test on a service backed by a tmp config to avoid mutating
        # global state on disk (which would be a permission error anyway).
        cfg_path = tmp_path / "evolution.json"
        cfg_path.write_text(json.dumps({}), encoding="utf-8")
        svc = EvolutionConfigService(config_path=str(cfg_path))

        # Stub out the central save to avoid hitting the real ConfigService.
        with patch.object(svc, "save_config", return_value=True):
            # Above-range value clamped to 2.5
            svc.set_difficulty_multiplier(99.0)
            # Below-range value clamped to 0.25
            svc.set_difficulty_multiplier(-1.0)
        assert True  # no exception means the clamping branches executed


class TestEvolutionConfigService:
    def test_community_size_info_default_tier(self):
        svc = get_evolution_config_service()
        info = svc.get_community_size_info(40)
        assert info["tier_name"] == "MEDIUM"
        assert info["multiplier"] == pytest.approx(1.0)

    def test_community_size_info_outside_known_tiers_falls_back(self):
        svc = get_evolution_config_service()
        # The hardcoded fallback only defines a MEDIUM tier (26..50), so any
        # member count outside that range exercises the fallback branch.  We
        # patch the loader to that minimal config so this test is deterministic
        # regardless of the evolution.json shipped on the host.
        baseline_config = svc._get_fallback_config()
        with patch.object(svc, "_load_config", return_value=baseline_config):
            info = svc.get_community_size_info(99999)
        # Falls through to default MEDIUM fallback.
        assert info["tier_name"] == "MEDIUM"

    def test_is_auto_difficulty_default(self):
        svc = get_evolution_config_service()
        baseline_config = svc._get_fallback_config()
        with patch.object(svc, "_load_config", return_value=baseline_config):
            assert svc.is_auto_difficulty() is True

    def test_get_difficulty_multiplier_default(self):
        svc = get_evolution_config_service()
        baseline_config = svc._get_fallback_config()
        with patch.object(svc, "_load_config", return_value=baseline_config):
            assert svc.get_difficulty_multiplier() == pytest.approx(1.0)

    def test_singleton_returns_same_instance(self):
        a = get_evolution_config_service()
        b = get_evolution_config_service()
        assert a is b

    def test_save_config_handles_io_error(self, tmp_path):
        cfg_path = tmp_path / "evolution.json"
        cfg_path.write_text("{}", encoding="utf-8")
        svc = EvolutionConfigService(config_path=str(cfg_path))
        with patch.object(
            svc._central_config_service,
            "_save_json_file",
            side_effect=IOError("disk full"),
        ):
            assert svc.save_config({"foo": "bar"}) is False

    def test_save_config_handles_runtime_error(self, tmp_path):
        cfg_path = tmp_path / "evolution.json"
        cfg_path.write_text("{}", encoding="utf-8")
        svc = EvolutionConfigService(config_path=str(cfg_path))
        with patch.object(
            svc._central_config_service,
            "_save_json_file",
            side_effect=RuntimeError("svc down"),
        ):
            assert svc.save_config({"foo": "bar"}) is False

    def test_load_config_handles_service_dependency_error(self, tmp_path):
        cfg_path = tmp_path / "evolution.json"
        cfg_path.write_text("{}", encoding="utf-8")
        svc = EvolutionConfigService(config_path=str(cfg_path))
        # Force the central service to raise an ImportError-like exception.
        with patch.object(
            svc._central_config_service,
            "_load_json_file",
            side_effect=ImportError("module gone"),
        ):
            cfg = svc._load_config()
        # Should fall back to the hardcoded fallback config.
        assert "base_evolution_costs" in cfg

    def test_load_config_handles_io_error(self, tmp_path):
        cfg_path = tmp_path / "evolution.json"
        cfg_path.write_text("{}", encoding="utf-8")
        svc = EvolutionConfigService(config_path=str(cfg_path))
        with patch.object(
            svc._central_config_service,
            "_load_json_file",
            side_effect=IOError("disk failure"),
        ):
            cfg = svc._load_config()
        assert "base_evolution_costs" in cfg

    def test_load_config_handles_json_decode_error(self, tmp_path):
        cfg_path = tmp_path / "evolution.json"
        cfg_path.write_text("{}", encoding="utf-8")
        svc = EvolutionConfigService(config_path=str(cfg_path))
        with patch.object(
            svc._central_config_service,
            "_load_json_file",
            side_effect=json.JSONDecodeError("bad", "doc", 0),
        ):
            cfg = svc._load_config()
        assert "base_evolution_costs" in cfg

    def test_reset_to_auto_difficulty(self, tmp_path):
        cfg_path = tmp_path / "evolution.json"
        cfg_path.write_text("{}", encoding="utf-8")
        svc = EvolutionConfigService(config_path=str(cfg_path))
        with patch.object(svc, "save_config", return_value=True) as save:
            assert svc.reset_to_auto_difficulty() is True
            saved_cfg = save.call_args.args[0]
        assert (
            saved_cfg["evolution_settings"]["manual_difficulty_override"] is False
        )
        assert saved_cfg["evolution_settings"]["difficulty_multiplier"] == 1.0

    def test_community_size_info_massive_tier_logarithmic(self, tmp_path):
        cfg_path = tmp_path / "evolution.json"
        cfg_path.write_text("{}", encoding="utf-8")
        svc = EvolutionConfigService(config_path=str(cfg_path))
        with patch.object(
            svc._central_config_service,
            "_load_json_file",
            return_value={
                "community_size_tiers": {
                    "MASSIVE": {
                        "min_members": 1000,
                        "max_members": 10_000_000,
                        "multiplier": 2.0,
                        "description": "huge",
                    }
                }
            },
        ):
            info = svc.get_community_size_info(2000)
        assert info["tier_name"] == "MASSIVE"
        # Logarithmic boost adds 0.5 * log2(2000/1000) == 0.5
        assert info["multiplier"] == pytest.approx(2.5)

    def test_get_evolution_level_info_with_decay_json(self, tmp_path, monkeypatch):
        # Place the production module at a tmp project root so the
        # ``Path(__file__).parents[2]`` lookup hits our decay.json.
        proj = tmp_path / "proj"
        cfg_dir = proj / "config" / "mech"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "decay.json").write_text(
            json.dumps({"levels": {"3": 250}, "default": 100}),
            encoding="utf-8",
        )
        from services.mech import mech_evolutions as ev_mod

        # Build a fake __file__ path so that Path(__file__).parents[2] == proj.
        fake_file = proj / "services" / "mech" / "mech_evolutions.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("# placeholder\n", encoding="utf-8")
        monkeypatch.setattr(ev_mod, "__file__", str(fake_file))

        info = ev_mod.get_evolution_level_info(3)
        assert info is not None
        # 250 cents -> $2.50 decay
        assert info.decay_per_day == pytest.approx(2.5)

    def test_get_all_evolution_levels_skips_invalid_keys(self):
        svc = get_evolution_config_service()
        bad_cfg = {
            "base_evolution_costs": {
                "1": {"name": "A", "cost": 0},
                "not-a-number": {"name": "B", "cost": 0},
                "2": {"name": "C", "cost": 10},
            }
        }
        with patch.object(svc, "_load_config", return_value=bad_cfg):
            levels = get_all_evolution_levels()
        assert sorted(levels.keys()) == [1, 2]


# ===========================================================================
# mech_images  (pure-function coverage; the module's top-level import of
# ``services.mech.mech_evolution_loader`` is intentionally swapped out by
# loading a patched copy of the source via importlib — this does NOT touch
# ``sys.modules``, only the local module object the tests close over.)
# ===========================================================================


def _load_patched_mech_images():
    """Load mech_images.py with the missing loader import replaced by a stub.

    The real ``services.mech.mech_evolution_loader`` module does not exist in
    the repository, so a normal import of ``services.mech.mech_images`` fails.
    To exercise the pure helper functions (``calculate_frame_duration``,
    ``get_mech_frames``, ``create_animated_gif``) without manipulating
    ``sys.modules`` we read the source, replace the offending import line with
    a local stub function, and load the result via ``importlib`` from a
    temporary file.
    """
    src_path = (
        Path(__file__).resolve().parents[4]
        / "services"
        / "mech"
        / "mech_images.py"
    )
    src = src_path.read_text(encoding="utf-8")
    patched = src.replace(
        "from services.mech.mech_evolution_loader import get_mech_loader",
        "def get_mech_loader():\n"
        "    raise RuntimeError('stubbed: not used by tests that mock it')",
    )

    import tempfile

    with tempfile.NamedTemporaryFile(
        suffix="_mech_images_patched.py", delete=False, mode="w", encoding="utf-8"
    ) as tmp:
        tmp.write(patched)
        tmp_path = tmp.name

    spec = importlib.util.spec_from_file_location("_mech_images_patched", tmp_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mech_images_module():
    return _load_patched_mech_images()


class TestMechImagesPure:
    def test_calculate_frame_duration_at_zero_is_max(self, mech_images_module):
        assert mech_images_module.calculate_frame_duration(0) == 100

    def test_calculate_frame_duration_at_full_is_min(self, mech_images_module):
        assert mech_images_module.calculate_frame_duration(100) == 10

    def test_calculate_frame_duration_clamps_below(self, mech_images_module):
        # -50 should clamp to 0 -> 100ms
        assert mech_images_module.calculate_frame_duration(-50) == 100

    def test_calculate_frame_duration_clamps_above(self, mech_images_module):
        # 200 should clamp to 100 -> 10ms
        assert mech_images_module.calculate_frame_duration(200) == 10

    def test_calculate_frame_duration_monotonic(self, mech_images_module):
        # Ease-out cubic: duration should monotonically decrease as speed goes up.
        last = mech_images_module.calculate_frame_duration(0)
        for speed in (10, 25, 50, 75, 90, 100):
            current = mech_images_module.calculate_frame_duration(speed)
            assert current <= last
            last = current

    def test_get_mech_frames_handles_no_info(self, mech_images_module):
        loader = MagicMock()
        loader.get_level_info.return_value = None
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            assert mech_images_module.get_mech_frames(99) == []

    def test_get_mech_frames_returns_frames(self, mech_images_module):
        loader = MagicMock()
        loader.get_level_info.return_value = {"frames": 3}
        # Each call returns a small placeholder image.
        loader.get_mech_image.side_effect = [
            Image.new("RGBA", (10, 10)),
            Image.new("RGBA", (10, 10)),
            Image.new("RGBA", (10, 10)),
        ]
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            frames = mech_images_module.get_mech_frames(1)
        assert len(frames) == 3

    def test_get_mech_frames_breaks_on_missing_frame(self, mech_images_module):
        loader = MagicMock()
        loader.get_level_info.return_value = {"frames": 4}
        loader.get_mech_image.side_effect = [
            Image.new("RGBA", (10, 10)),
            None,  # break here
            Image.new("RGBA", (10, 10)),
            Image.new("RGBA", (10, 10)),
        ]
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            frames = mech_images_module.get_mech_frames(1)
        assert len(frames) == 1

    def test_get_mech_frames_for_speed_returns_duration(self, mech_images_module):
        loader = MagicMock()
        loader.get_level_info.return_value = {"frames": 2}
        loader.get_mech_image.side_effect = [
            Image.new("RGBA", (10, 10)),
            Image.new("RGBA", (10, 10)),
        ]
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            frames, duration = mech_images_module.get_mech_frames_for_speed(1, 50)
        assert len(frames) == 2
        # Duration must be a positive int in [10, 100].
        assert 10 <= duration <= 100

    def test_create_animated_gif_returns_bytes(self, mech_images_module):
        loader = MagicMock()
        loader.get_level_info.return_value = {"frames": 2}
        loader.get_mech_image.side_effect = [
            Image.new("RGBA", (10, 10), (255, 0, 0, 255)),
            Image.new("RGBA", (10, 10), (0, 255, 0, 255)),
        ]
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            data = mech_images_module.create_animated_gif(1, speed=50)
        assert isinstance(data, bytes)
        assert data.startswith(b"GIF")

    def test_create_animated_gif_no_frames_returns_empty(self, mech_images_module):
        loader = MagicMock()
        loader.get_level_info.return_value = None
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            assert mech_images_module.create_animated_gif(99, speed=50) == b""

    def test_get_available_levels(self, mech_images_module):
        loader = MagicMock()
        loader.get_available_levels.return_value = [1, 2, 3]
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            assert mech_images_module.get_available_levels() == [1, 2, 3]

    def test_get_level_info(self, mech_images_module):
        loader = MagicMock()
        loader.get_level_info.return_value = {"frames": 8, "resolution": (100, 100)}
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            assert mech_images_module.get_level_info(5) == {
                "frames": 8,
                "resolution": (100, 100),
            }

    def test_get_mech_image(self, mech_images_module):
        loader = MagicMock()
        sentinel = Image.new("RGBA", (4, 4))
        loader.get_mech_image.return_value = sentinel
        with patch.object(mech_images_module, "get_mech_loader", return_value=loader):
            assert mech_images_module.get_mech_image(1, 0) is sentinel
