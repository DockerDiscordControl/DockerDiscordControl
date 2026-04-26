# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Animation Cache Service Tests                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Functional unit tests for ``services.mech.animation_cache_service``.

Goal: lift the per-module coverage from ~21% to >=65% by exercising the
public surface (helpers, dataclasses, cache lifecycle, fast-path/disk-cache
flow, status-overview/discord-optimized wrappers, event handlers and the
warm-up coordinator).

Hard rules:
  * Never mutate ``sys.modules`` -- isolation is achieved exclusively with
    ``unittest.mock.patch`` / ``monkeypatch.setattr``.
  * Heavy collaborators (PIL, MechHighResService, MechDataStore,
    MechWebService, EventManager, speed_levels) are stubbed.
  * Each test uses ``tmp_path`` for cache_dir isolation so the suite is
    safe to run in parallel with other tests.
"""

from __future__ import annotations

import os
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from services.mech.animation_cache_service import (
    AnimationCacheService,
    MechAnimationRequest,
    MechAnimationResult,
    get_animation_cache_service,
)


# ---------------------------------------------------------------------------
# Service factory: construct an AnimationCacheService that does NOT touch
# real disk paths or wire up real event listeners. All collaborators that
# would otherwise fail at construction time are stubbed via patch-context.
# ---------------------------------------------------------------------------
def _make_service(tmp_path: Path) -> AnimationCacheService:
    """Build an AnimationCacheService bound to ``tmp_path`` with all
    side-effecting collaborators stubbed (event listeners, disk eviction).
    """
    with patch.object(
        AnimationCacheService, "_setup_event_listeners", lambda self: None
    ), patch.object(
        AnimationCacheService,
        "enforce_disk_cache_limit",
        lambda self, *a, **kw: 0,
    ), patch.dict(os.environ, {"DDC_ANIM_DISK_LIMIT_MB": "0"}):
        svc = AnimationCacheService()
    svc.cache_dir = tmp_path
    svc._focused_cache.clear()
    svc._walk_scale_factors.clear()
    return svc


@pytest.fixture
def svc(tmp_path: Path) -> AnimationCacheService:
    return _make_service(tmp_path)


# ===========================================================================
# 1. Pure helper functions
# ===========================================================================
class TestQuantizeSpeed:
    def test_zero_preserved(self, svc):
        assert svc._quantize_speed(0) == 0.0

    def test_negative_clamped_to_zero(self, svc):
        assert svc._quantize_speed(-5) == 0.0

    def test_max_speed_101_preserved(self, svc):
        assert svc._quantize_speed(101) == 101.0

    def test_above_101_capped(self, svc):
        assert svc._quantize_speed(150) == 101.0

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (1, 5.0),    # below 5 still clamped to 5
            (5, 5.0),
            (7, 5.0),    # rounds down
            (8, 10.0),   # rounds up
            (50, 50.0),
            (52, 50.0),
            (53, 55.0),
            (97, 95.0),
            (98, 100.0),
            (100, 100.0),
        ],
    )
    def test_5pct_buckets(self, svc, raw, expected):
        assert svc._quantize_speed(raw) == expected


class TestCacheKey:
    def test_format(self, svc):
        assert svc._get_cache_key(3, 50.0, "walk", "small") == "L3_walk_small_S50"

    def test_speed_truncated_to_int(self, svc):
        # The format string casts via int(), so 55.9 becomes 55.
        assert svc._get_cache_key(11, 55.9, "rest", "big") == "L11_rest_big_S55"


class TestObfuscateRoundTrip:
    @pytest.mark.parametrize(
        "payload",
        [
            b"",
            b"a",
            b"\x00\x01\x02\x03",
            b"MechAnimCache2024",  # exactly the XOR key length
            b"x" * 1024,
            b"\xff\xfe\xfd\xfc\xfb\xfa\xf9",
        ],
    )
    def test_xor_is_symmetric(self, svc, payload):
        obf = svc._obfuscate_data(payload)
        assert svc._deobfuscate_data(obf) == payload

    def test_obfuscation_changes_data(self, svc):
        payload = b"hello world this is plaintext"
        assert svc._obfuscate_data(payload) != payload


# ===========================================================================
# 2. RAM (LRU) cache behaviour
# ===========================================================================
class TestRamCache:
    def test_store_and_get(self, svc):
        svc._store_in_ram_cache("key-A", b"AAA")
        assert svc._get_from_ram_cache("key-A") == b"AAA"

    def test_miss_returns_none(self, svc):
        assert svc._get_from_ram_cache("missing") is None

    def test_lru_evicts_oldest_when_full(self, svc):
        # maxsize=4
        for i in range(4):
            svc._store_in_ram_cache(f"k{i}", f"v{i}".encode())
        assert svc._get_from_ram_cache("k0") == b"v0"

        # Adding a fifth entry must evict the LRU element ("k0" if untouched,
        # but we just touched it via the previous get -> evict "k1" instead).
        svc._store_in_ram_cache("k4", b"v4")
        assert len(svc._focused_cache) == 4
        assert svc._get_from_ram_cache("k1") is None
        assert svc._get_from_ram_cache("k4") == b"v4"


# ===========================================================================
# 3. Canvas-size lookup table
# ===========================================================================
class TestCanvasSize:
    @pytest.mark.parametrize(
        "level,expected_h",
        [
            (1, 100), (2, 100), (3, 100),
            (4, 150), (5, 150),
            (6, 170),
            (7, 100), (8, 100),
            (9, 230), (10, 250), (11, 270),
        ],
    )
    def test_walk_heights_per_level(self, svc, level, expected_h):
        assert svc.get_expected_canvas_size(level, "walk") == (270, expected_h)

    @pytest.mark.parametrize(
        "level,expected_h",
        [
            (1, 160), (2, 160), (3, 160),
            (4, 210), (5, 210),
            (6, 230),
            (7, 160), (8, 160),
            (9, 290), (10, 310),
        ],
    )
    def test_rest_heights_levels_1_to_10(self, svc, level, expected_h):
        assert svc.get_expected_canvas_size(level, "rest") == (270, expected_h)

    def test_rest_level_11_falls_back_to_walk(self, svc):
        # Level 11 has no rest animation -> walk height (270)
        assert svc.get_expected_canvas_size(11, "rest") == (270, 270)

    def test_status_overview_one_third_height(self, svc):
        # Spot-check a couple: level 1 -> 34, level 11 -> 90
        assert svc.get_expected_canvas_size(1, "status_overview") == (270, 34)
        assert svc.get_expected_canvas_size(11, "status_overview") == (270, 90)
        assert svc.get_expected_canvas_size(9, "status_overview") == (270, 77)

    def test_unknown_animation_type_uses_walk_table(self, svc):
        # any non-rest, non-status_overview falls into the walk branch
        assert svc.get_expected_canvas_size(5, "unexpected") == (270, 150)

    def test_big_resolution_delegates_to_high_res_service(self, svc):
        fake_hr = MagicMock()
        fake_hr.get_canvas_size_for_resolution.return_value = (540, 540)
        with patch(
            "services.mech.mech_high_res_service.get_mech_high_res_service",
            return_value=fake_hr,
        ):
            size = svc.get_expected_canvas_size(7, "walk", resolution="big")
        assert size == (540, 540)
        fake_hr.get_canvas_size_for_resolution.assert_called_once_with(
            7, "big", "walk"
        )

    def test_unknown_level_falls_back(self, svc):
        # level 99 isn't in walk_heights -> default 100
        assert svc.get_expected_canvas_size(99, "walk") == (270, 100)
        # level 99 isn't in status_overview map -> fallback 34
        assert svc.get_expected_canvas_size(99, "status_overview") == (270, 34)


# ===========================================================================
# 4. Cached-animation path resolution
# ===========================================================================
class TestCachedAnimationPath:
    def test_small_walk_existing_file_returns_direct(self, svc, tmp_path):
        f = tmp_path / "mech_3_100speed.cache"
        f.write_bytes(b"x")
        path = svc.get_cached_animation_path(3, "walk", "small")
        assert path == f

    def test_small_rest_filename(self, svc, tmp_path):
        # File doesn't exist; folder lookup also fails because assets_dir is
        # None in V2.0 (we'll set it explicitly to None to be sure).
        svc.assets_dir = None
        path = svc.get_cached_animation_path(2, "rest", "small")
        assert path.name == "mech_2_rest_100speed.cache"

    def test_big_walk_filename(self, svc, tmp_path):
        svc.assets_dir = None
        path = svc.get_cached_animation_path(5, "walk", "big")
        assert path.name == "mech_5_100speed_big.cache"

    def test_big_rest_filename(self, svc, tmp_path):
        svc.assets_dir = None
        path = svc.get_cached_animation_path(7, "rest", "big")
        assert path.name == "mech_7_rest_100speed_big.cache"


# ===========================================================================
# 5. cleanup_old_animations + clear_cache
# ===========================================================================
class TestCleanupAndClear:
    def test_keep_hours_zero_removes_all_cache_files(self, svc, tmp_path):
        for n in ("mech_1_100speed.cache", "mech_2_100speed.cache",
                  "mech_3_rest_100speed.cache"):
            (tmp_path / n).write_bytes(b"x")
        # Also put a non-cache file -> must NOT be touched.
        (tmp_path / "ignore.txt").write_text("keep")

        svc.cleanup_old_animations(keep_hours=0)

        assert list(tmp_path.glob("*.cache")) == []
        assert (tmp_path / "ignore.txt").exists()

    def test_keep_hours_age_based_only_removes_old(self, svc, tmp_path):
        old = tmp_path / "mech_1_100speed.cache"
        old.write_bytes(b"x")
        new = tmp_path / "mech_2_100speed.cache"
        new.write_bytes(b"y")

        # Age `old` 25h
        ancient = time.time() - (25 * 3600)
        os.utime(old, (ancient, ancient))

        svc.cleanup_old_animations(keep_hours=24)

        assert not old.exists()
        assert new.exists()

    def test_clear_cache_calls_cleanup_with_zero(self, svc, tmp_path):
        (tmp_path / "mech_1_100speed.cache").write_bytes(b"x")
        with patch.object(
            svc, "cleanup_old_animations", wraps=svc.cleanup_old_animations
        ) as wrapped:
            svc.clear_cache()
        wrapped.assert_called_once_with(keep_hours=0)
        assert list(tmp_path.glob("*.cache")) == []


# ===========================================================================
# 6. enforce_disk_cache_limit edge cases
# ===========================================================================
class TestEnforceDiskCacheLimit:
    def test_zero_max_returns_zero_immediately(self, svc, tmp_path):
        (tmp_path / "mech_L1_walk_small_S5.webp").write_bytes(b"x" * 1024)
        assert svc.enforce_disk_cache_limit(max_mb=0) == 0

    def test_under_limit_returns_zero(self, svc, tmp_path):
        (tmp_path / "mech_L1_walk_small_S5.webp").write_bytes(b"x" * 1024)
        assert svc.enforce_disk_cache_limit(max_mb=1) == 0

    def test_over_limit_evicts_oldest(self, svc, tmp_path):
        now = time.time()
        # Two large files, neither alone over 1MB but together 2MB.
        oldest = tmp_path / "mech_L1_walk_small_S5.webp"
        oldest.write_bytes(b"o" * 1024 * 1024)  # 1 MB
        os.utime(oldest, (now - 86400, now - 86400))

        newer = tmp_path / "mech_L1_walk_small_S10.webp"
        newer.write_bytes(b"n" * 1024 * 1024)  # 1 MB
        os.utime(newer, (now, now))

        removed = svc.enforce_disk_cache_limit(max_mb=1)
        assert removed >= 1
        assert not oldest.exists(), "Oldest must go first (LRU)"
        # newer survives (we only need to drop ~1MB to be at or under limit)
        assert newer.exists()

    def test_cache_files_never_evicted(self, svc, tmp_path):
        big_cache = tmp_path / "mech_5_100speed.cache"
        big_cache.write_bytes(b"c" * 5 * 1024 * 1024)
        webp = tmp_path / "mech_L1_walk_small_S5.webp"
        webp.write_bytes(b"w" * 50 * 1024)

        svc.enforce_disk_cache_limit(max_mb=1)
        assert big_cache.exists()
        assert webp.exists()

    def test_handles_oserror_gracefully(self, svc, tmp_path):
        # glob() raising OSError -> function returns 0 silently.
        with patch.object(
            type(svc.cache_dir),
            "glob",
            side_effect=OSError("boom"),
        ):
            assert svc.enforce_disk_cache_limit(max_mb=1) == 0


# ===========================================================================
# 7. _get_animation_internal: fast path / disk hit / regen
# ===========================================================================
class TestGetAnimationInternal:
    def test_ram_cache_hit_short_circuits(self, svc):
        key = svc._get_cache_key(5, 50.0, "walk", "small")
        svc._store_in_ram_cache(key, b"RAM_DATA")

        # Force base path to NOT exist; we should never reach disk.
        with patch("builtins.open", side_effect=AssertionError("disk hit"))\
                , patch.object(svc, "_apply_speed_to_animation",
                                side_effect=AssertionError("reencode")):
            out = svc._get_animation_internal(5, 50, 1.0, "small")
        assert out == b"RAM_DATA"

    def test_fast_path_reads_base_file_and_caches(self, svc, tmp_path):
        payload = b"BASE_FRAMES_OK"
        base = svc.get_cached_animation_path(4, "walk", "small")
        base.write_bytes(svc._obfuscate_data(payload))

        with patch.object(svc, "_apply_speed_to_animation",
                          side_effect=AssertionError("must not re-encode")):
            out = svc._get_animation_internal(4, 50, 1.0, "small")
        assert out == payload

        # Second call should be a RAM cache hit (we removed disk file to prove)
        base.unlink()
        out2 = svc._get_animation_internal(4, 50, 1.0, "small")
        assert out2 == payload

    def test_level_11_always_fast_path(self, svc, tmp_path):
        payload = b"LEVEL11_DATA"
        base = svc.get_cached_animation_path(11, "walk", "small")
        base.write_bytes(svc._obfuscate_data(payload))

        with patch.object(svc, "_apply_speed_to_animation",
                          side_effect=AssertionError("no re-encoding")):
            # Even at quantised speed=80 (not base) level 11 fast-paths.
            out = svc._get_animation_internal(11, 80, 1.0, "small")
        assert out == payload

    def test_rest_animation_returns_base_no_reencoding(self, svc, tmp_path):
        # power=0, level<=10 => animation_type=='rest'.
        payload = b"REST_BASE_DATA"
        base = svc.get_cached_animation_path(3, "rest", "small")
        base.write_bytes(svc._obfuscate_data(payload))

        with patch.object(svc, "_apply_speed_to_animation",
                          side_effect=AssertionError("no re-encoding")):
            out = svc._get_animation_internal(3, 50, 0.0, "small")
        assert out == payload

    def test_disk_speed_cache_hit(self, svc, tmp_path):
        # Quantised speed 80 != base, so neither fast path nor rest applies.
        # If a speed-cache file exists we should read it directly without
        # touching the re-encoder.
        adjusted = b"ALREADY_ADJUSTED_80"
        speed_path = tmp_path / "mech_L5_walk_small_S80.webp"
        speed_path.write_bytes(adjusted)

        # Provide a base file too (otherwise the regen path would fire if
        # disk-cache somehow misses).
        base = svc.get_cached_animation_path(5, "walk", "small")
        base.write_bytes(svc._obfuscate_data(b"BASE"))

        with patch.object(svc, "_apply_speed_to_animation",
                          side_effect=AssertionError("disk cache should hit")):
            out = svc._get_animation_internal(5, 80, 1.0, "small")
        assert out == adjusted

    def test_regen_path_calls_speed_adjuster_and_writes_disk_cache(
        self, svc, tmp_path
    ):
        base_payload = b"BASE_RAW"
        base = svc.get_cached_animation_path(5, "walk", "small")
        base.write_bytes(svc._obfuscate_data(base_payload))

        adjusted = b"ADJUSTED_OUTPUT"
        with patch.object(
            svc, "_apply_speed_to_animation", return_value=adjusted
        ) as mock_apply:
            out = svc._get_animation_internal(5, 80, 1.0, "small")

        mock_apply.assert_called_once()
        called_args, _ = mock_apply.call_args
        assert called_args[0] == base_payload
        assert out == adjusted

        # Disk cache file written? speed=80 quantises to 80, so filename=...S80.
        speed_path = tmp_path / "mech_L5_walk_small_S80.webp"
        assert speed_path.exists()
        assert speed_path.read_bytes() == adjusted

    def test_missing_base_triggers_pre_generate_then_returns_empty_when_assets_none(
        self, svc, tmp_path
    ):
        # No base file, assets_dir is None => pre_generate_animation is a no-op
        # and _get_animation_internal should return b"".
        svc.assets_dir = None
        out = svc._get_animation_internal(5, 80, 1.0, "small")
        assert out == b""

    def test_base_read_error_logged_and_falls_through(self, svc, tmp_path):
        # Fast path: open() raises -> warning logged, fall-through to regen.
        base = svc.get_cached_animation_path(5, "walk", "small")
        base.write_bytes(svc._obfuscate_data(b"BASE_DATA"))

        # First call to open (fast-path) raises; second call (regen step)
        # returns the real bytes via the actual builtin.
        real_open = open
        calls = {"count": 0}

        def flaky_open(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise IOError("transient read failure")
            return real_open(*args, **kwargs)

        with patch("builtins.open", side_effect=flaky_open):
            with patch.object(svc, "_apply_speed_to_animation",
                              return_value=b"OK") as mock_re:
                # speed=50 is the fast-path; flaky_open trips fast-path read.
                # After exception, fall-through hits the regen branch which
                # also opens the base file -> succeeds (real open).
                out = svc._get_animation_internal(5, 50, 1.0, "small")
        # is_base_speed branch in regen will short-circuit and return base data
        assert out == b"BASE_DATA"
        # Re-encoder must NOT have been invoked because is_base_speed True
        mock_re.assert_not_called()


# ===========================================================================
# 8. Public wrappers around _get_animation_internal
# ===========================================================================
class TestPublicWrappers:
    def test_get_animation_with_speed_and_power_routes_small(self, svc):
        with patch.object(svc, "_get_animation_internal", return_value=b"S") as m:
            out = svc.get_animation_with_speed_and_power(3, 50, 1.0)
        assert out == b"S"
        assert m.call_args.kwargs.get("resolution", "small") == "small"

    def test_get_animation_with_speed_and_power_big_routes_big(self, svc):
        with patch.object(svc, "_get_animation_internal", return_value=b"B") as m:
            out = svc.get_animation_with_speed_and_power_big(3, 50, 1.0)
        assert out == b"B"
        assert m.call_args.kwargs.get("resolution") == "big"

    def test_get_animation_with_speed_legacy_uses_power_one(self, svc):
        with patch.object(svc, "_get_animation_internal", return_value=b"L") as m:
            out = svc.get_animation_with_speed(3, 50)
        assert out == b"L"
        called = m.call_args
        assert called.kwargs.get("power_level") == 1.0
        assert called.kwargs.get("resolution") == "small"


# ===========================================================================
# 9. Service First wrapper: get_mech_animation
# ===========================================================================
class TestGetMechAnimation:
    def test_invalid_level_returns_failure(self, svc):
        result = svc.get_mech_animation(MechAnimationRequest(evolution_level=0))
        assert result.success is False
        assert "Invalid evolution level" in result.error_message

        result2 = svc.get_mech_animation(MechAnimationRequest(evolution_level=12))
        assert result2.success is False

    def test_success_walk_animation(self, svc):
        with patch.object(
            svc, "get_animation_with_speed_and_power", return_value=b"WEBP"
        ):
            result = svc.get_mech_animation(
                MechAnimationRequest(evolution_level=4, power_level=1.0,
                                     speed_level=50.0)
            )
        assert result.success is True
        assert result.animation_bytes == b"WEBP"
        assert result.animation_type == "walk"
        assert result.evolution_level == 4
        assert result.canvas_size == (270, 150)
        assert result.actual_speed_level == 50.0
        assert result.generation_time_ms >= 0.0
        assert result.cache_hit is False  # include_metadata default False

    def test_rest_animation_when_power_zero_and_level_low(self, svc):
        with patch.object(
            svc, "get_animation_with_speed_and_power", return_value=b"REST"
        ):
            result = svc.get_mech_animation(
                MechAnimationRequest(
                    evolution_level=3, power_level=0.0, speed_level=50.0,
                )
            )
        assert result.success is True
        assert result.animation_type == "rest"
        # canvas: rest level 3 -> (270, 160)
        assert result.canvas_size == (270, 160)

    def test_metadata_populates_cache_key_and_hit_flag(self, svc):
        with patch.object(
            svc, "get_animation_with_speed_and_power", return_value=b"OK"
        ):
            result = svc.get_mech_animation(
                MechAnimationRequest(
                    evolution_level=2, power_level=1.0, speed_level=42.0,
                    include_metadata=True,
                )
            )
        assert result.success is True
        assert result.cache_key == "mech_2_walk_42.0"
        # Should be a fast call -> cache_hit True
        assert isinstance(result.cache_hit, bool)

    def test_io_error_caught_and_reported(self, svc):
        with patch.object(
            svc, "get_animation_with_speed_and_power",
            side_effect=IOError("disk gone"),
        ):
            result = svc.get_mech_animation(
                MechAnimationRequest(evolution_level=3)
            )
        assert result.success is False
        assert "File I/O error" in result.error_message
        assert result.generation_time_ms >= 0.0

    def test_value_error_caught_and_reported(self, svc):
        with patch.object(
            svc, "get_animation_with_speed_and_power",
            side_effect=ValueError("bad data"),
        ):
            result = svc.get_mech_animation(
                MechAnimationRequest(evolution_level=3)
            )
        assert result.success is False
        assert "Data processing error" in result.error_message


# ===========================================================================
# 10. Cache invalidation methods
# ===========================================================================
class TestCacheInvalidation:
    def test_memory_cache_only_clears_ram(self, svc, tmp_path):
        svc._store_in_ram_cache("k", b"v")
        # Files on disk should NOT be touched.
        kept = tmp_path / "mech_1_100speed.cache"
        kept.write_bytes(b"x")

        svc.invalidate_memory_cache_only("test")
        assert len(svc._focused_cache) == 0
        assert kept.exists()

    def test_full_invalidation_clears_disk_and_ram(self, svc, tmp_path):
        svc._store_in_ram_cache("k", b"v")
        cache = tmp_path / "mech_1_100speed.cache"
        cache.write_bytes(b"c")
        speed = tmp_path / "mech_L1_walk_small_S50.webp"
        speed.write_bytes(b"s")
        # A file that does NOT match either glob should be preserved.
        other = tmp_path / "unrelated.txt"
        other.write_text("keep")

        svc.invalidate_animation_cache("manual reset")

        assert len(svc._focused_cache) == 0
        assert not cache.exists()
        assert not speed.exists()
        assert other.exists()


# ===========================================================================
# 11. get_cache_status
# ===========================================================================
class TestCacheStatus:
    def test_empty_cache(self, svc):
        st = svc.get_cache_status()
        assert st["cache_type"] == "LRUCache"
        assert st["total_entries"] == 0
        assert st["max_entries"] == 4
        assert st["memory_usage_bytes"] == 0
        assert st["entries_detail"] == {}
        assert "current_state" in st

    def test_populated_cache_reports_sizes(self, svc):
        svc._store_in_ram_cache("a", b"x" * 1024)
        svc._store_in_ram_cache("b", b"y" * 2048)
        st = svc.get_cache_status()
        assert st["total_entries"] == 2
        assert st["memory_usage_bytes"] == 1024 + 2048
        # entries_detail mapping has both keys with size_bytes/size_mb/type.
        for k in ("a", "b"):
            entry = st["entries_detail"][k]
            assert entry["type"] == "ram_cache"
            assert "size_bytes" in entry
            assert "size_mb" in entry

    def test_update_state_tracks_walk_vs_rest(self, svc):
        svc._update_current_state(level=5, speed=50.0, power=1.0)
        assert svc._current_animation_type == "walk"
        svc._update_current_state(level=5, speed=50.0, power=0.0)
        assert svc._current_animation_type == "rest"
        svc._update_current_state(level=11, speed=100.0, power=0.0)
        # Level 11 with power 0 -> still walk (level>10 disqualifies rest)
        assert svc._current_animation_type == "walk"


# ===========================================================================
# 12. Event handler entry points
# ===========================================================================
class TestEventHandlers:
    def test_handle_donation_event_invalidates_ram_only(self, svc):
        svc._store_in_ram_cache("k", b"v")
        event_data = SimpleNamespace(data={"amount": "5.00"})

        # Avoid the proactive re-cache path by patching asyncio internals.
        # When no event loop is running and _sync_recache fires, swallow it.
        with patch.object(svc, "_sync_recache_current_animations") as mock_sync:
            svc._handle_donation_event(event_data)

        assert len(svc._focused_cache) == 0
        # We should have requested a sync recache (no running event loop in tests).
        mock_sync.assert_called_once()

    def test_handle_state_change_significant_invalidates(self, svc):
        svc._store_in_ram_cache("k", b"v")
        # threshold default = 1.0
        event = SimpleNamespace(data={"old_power": 5.0, "new_power": 10.0})
        with patch.object(svc, "_sync_recache_current_animations") as mock_sync:
            svc._handle_state_change_event(event)
        assert len(svc._focused_cache) == 0
        mock_sync.assert_called_once()

    def test_handle_state_change_minor_ignored(self, svc):
        svc._store_in_ram_cache("k", b"v")
        event = SimpleNamespace(data={"old_power": 5.0, "new_power": 5.5})
        with patch.object(svc, "_sync_recache_current_animations") as mock_sync:
            svc._handle_state_change_event(event)
        # Minor change -> RAM cache untouched, no recache scheduled.
        assert len(svc._focused_cache) == 1
        mock_sync.assert_not_called()

    def test_handle_donation_event_swallows_bad_payload(self, svc):
        # Missing .data attribute -> AttributeError caught gracefully.
        event_data = SimpleNamespace()
        # Should NOT raise.
        svc._handle_donation_event(event_data)

    def test_handle_state_change_swallows_bad_payload(self, svc):
        event_data = SimpleNamespace()  # No .data
        svc._handle_state_change_event(event_data)


# ===========================================================================
# 13. Pre-generation skip paths (V2.0 cache-only behaviour)
# ===========================================================================
class TestPreGenerateSkipPaths:
    def test_pre_generate_animation_skips_when_already_cached(self, svc, tmp_path):
        cache_path = svc.get_cached_animation_path(2, "walk", "small")
        cache_path.write_bytes(b"existing")

        # _load_and_process_frames must NOT be called.
        with patch.object(svc, "_load_and_process_frames",
                          side_effect=AssertionError("should be skipped")):
            svc.pre_generate_animation(2, "walk", "small")

    def test_pre_generate_animation_skips_when_assets_none(self, svc):
        # Simulate Docker V2.0 cache-only environment.
        svc.assets_dir = None
        # Should silently log and return without raising.
        svc.pre_generate_animation(99, "walk", "small")

    def test_pre_generate_all_animations_no_assets(self, svc):
        svc.assets_dir = None
        svc.pre_generate_all_animations()  # no-op, no exception

    def test_pre_generate_all_rest_animations_no_assets(self, svc):
        svc.assets_dir = None
        svc.pre_generate_all_rest_animations()

    def test_pre_generate_all_big_animations_no_assets(self, svc):
        svc.assets_dir = None
        svc.pre_generate_all_big_animations()

    def test_pre_generate_rest_skips_level_11(self, svc):
        # Level 11 has no rest animation; method returns silently.
        with patch.object(svc, "pre_generate_animation",
                          side_effect=AssertionError("should not reach")):
            svc.pre_generate_rest_animation(11)

    def test_pre_generate_rest_delegates_for_low_level(self, svc):
        with patch.object(svc, "pre_generate_animation") as m:
            svc.pre_generate_rest_animation(3)
        m.assert_called_once_with(3, "rest")

    def test_pre_generate_big_animation_delegates(self, svc):
        with patch.object(svc, "pre_generate_animation") as m:
            svc.pre_generate_big_animation(5, "walk")
        m.assert_called_once_with(5, "walk", "big")


# ===========================================================================
# 14. _create_unified_webp / _apply_speed_to_animation - functional roundtrip
# ===========================================================================
def _make_webp_animation(size=(8, 8), n_frames=2, duration=125) -> bytes:
    """Build a tiny real-WebP animation in-memory using PIL."""
    from PIL import Image
    frames = [Image.new("RGBA", size, (i * 10, 0, 0, 255)) for i in range(n_frames)]
    buf = BytesIO()
    frames[0].save(
        buf, format="WebP", save_all=True, append_images=frames[1:],
        duration=duration, loop=0, lossless=True, quality=100, method=6,
    )
    return buf.getvalue()


class TestWebPRoundtrip:
    def test_create_unified_webp_returns_bytes(self, svc):
        from PIL import Image
        frames = [Image.new("RGBA", (4, 4), (0, 0, 0, 255)) for _ in range(2)]
        out = svc._create_unified_webp(frames, base_duration=125)
        assert isinstance(out, bytes) and len(out) > 0

    def test_apply_speed_returns_bytes_for_real_webp(self, svc):
        webp = _make_webp_animation()
        adjusted = svc._apply_speed_to_animation(webp, speed_level=80.0)
        assert isinstance(adjusted, bytes) and len(adjusted) > 0

    def test_apply_speed_falls_back_to_input_on_error(self, svc):
        # Garbage input -> Image.open raises -> fallback returns original bytes.
        garbage = b"not a webp"
        out = svc._apply_speed_to_animation(garbage, speed_level=50.0)
        assert out == garbage


# ===========================================================================
# 15. Singleton accessor
# ===========================================================================
class TestSingleton:
    def test_returns_same_instance(self, monkeypatch):
        # Reset the module-level singleton.
        import services.mech.animation_cache_service as mod
        monkeypatch.setattr(mod, "_animation_cache_service", None)
        # Avoid touching real disks during construction.
        with patch.object(
            AnimationCacheService, "_setup_event_listeners", lambda self: None
        ), patch.object(
            AnimationCacheService,
            "enforce_disk_cache_limit",
            lambda self, *a, **kw: 0,
        ):
            inst1 = get_animation_cache_service()
            inst2 = get_animation_cache_service()
        assert inst1 is inst2

        # Reset singleton again to keep test isolation.
        monkeypatch.setattr(mod, "_animation_cache_service", None)


# ===========================================================================
# 16. Dataclass smoke / defaults
# ===========================================================================
class TestDataclasses:
    def test_request_defaults(self):
        req = MechAnimationRequest(evolution_level=3)
        assert req.power_level == 1.0
        assert req.speed_level == 50.0
        assert req.include_metadata is False
        assert req.resolution == "small"

    def test_result_defaults(self):
        res = MechAnimationResult(success=False)
        assert res.animation_bytes is None
        assert res.evolution_level == 0
        assert res.animation_type == ""
        assert res.cache_hit is False
        assert res.cache_key == ""
        assert res.error_message is None


# ===========================================================================
# 17. get_status_overview_animation - happy path with mocked PIL
# ===========================================================================
class TestStatusOverviewAnimation:
    def test_returns_bytes_with_mocked_pipeline(self, svc):
        """status overview pipeline is exercised end-to-end with a small
        real WebP (so PIL doesn't blow up) and stubbed speed-levels."""
        webp_bytes = _make_webp_animation(size=(20, 20), n_frames=2)
        with patch.object(
            svc, "get_animation_with_speed_and_power", return_value=webp_bytes
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            return_value={"speed": {"level": 50}},
        ):
            out = svc.get_status_overview_animation(5, power_level=1.0)
        assert isinstance(out, bytes)
        # The status-overview produces a non-trivial WebP.
        assert len(out) > 0

    def test_level_11_uses_max_speed(self, svc):
        webp_bytes = _make_webp_animation()
        # If we reach get_combined_mech_status the test fails; level 11 must
        # bypass that lookup entirely.
        with patch.object(
            svc, "get_animation_with_speed_and_power", return_value=webp_bytes
        ) as m, patch(
            "services.mech.speed_levels.get_combined_mech_status",
            side_effect=AssertionError("must not be called for level 11"),
        ):
            svc.get_status_overview_animation(11, power_level=1.0)
        # Speed level passed to inner method must be 100 (divine speed).
        called_args = m.call_args[0]
        assert called_args[1] == 100

    def test_io_error_returns_fallback_canvas(self, svc):
        with patch.object(
            svc, "get_animation_with_speed_and_power",
            side_effect=IOError("disk failure"),
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            return_value={"speed": {"level": 50}},
        ):
            out = svc.get_status_overview_animation(3, power_level=1.0)
        # Fallback transparent canvas is still a valid bytes blob.
        assert isinstance(out, bytes)
        assert len(out) > 0


# ===========================================================================
# 18. get_discord_optimized_animation - "zero scaling" pass-through
# ===========================================================================
class TestDiscordOptimizedAnimation:
    def test_passthrough_returns_input_bytes(self, svc):
        webp = _make_webp_animation()
        with patch.object(
            svc, "get_animation_with_speed_and_power", return_value=webp
        ):
            out = svc.get_discord_optimized_animation(5, power_level=1.0)
        # Zero-scaling: same bytes back.
        assert out == webp

    def test_io_error_returns_fallback_bytes(self, svc):
        with patch.object(
            svc, "get_animation_with_speed_and_power",
            side_effect=IOError("disk failure"),
        ):
            out = svc.get_discord_optimized_animation(3, power_level=0.0)
        assert isinstance(out, bytes)
        assert len(out) > 0

    def test_value_error_returns_fallback_bytes(self, svc):
        with patch.object(
            svc, "get_animation_with_speed_and_power",
            side_effect=ValueError("bad data"),
        ):
            out = svc.get_discord_optimized_animation(3, power_level=1.0)
        assert isinstance(out, bytes)
        assert len(out) > 0


# ===========================================================================
# 19. _smart_crop_frames + _get_bbox_with_alpha_threshold
# ===========================================================================
class TestSmartCropAndBbox:
    def test_smart_crop_empty_input(self, svc):
        assert svc._smart_crop_frames([]) == []

    def test_smart_crop_no_content_returns_unchanged(self, svc):
        # All-transparent frames -> bbox is None for every frame -> early
        # return (original frames as-is).
        from PIL import Image
        f1 = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        f2 = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
        out = svc._smart_crop_frames([f1, f2])
        assert out == [f1, f2]

    def test_smart_crop_with_visible_pixel_crops_to_bbox(self, svc):
        from PIL import Image
        f1 = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        # Put one opaque pixel at (5, 5)
        f1.putpixel((5, 5), (255, 255, 255, 255))
        f2 = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        f2.putpixel((10, 10), (255, 0, 0, 255))
        cropped = svc._smart_crop_frames([f1, f2])
        # Original 20x20 -> bbox (5,5)-(11,11), padding 2 -> (3,3)-(13,13)=10x10
        assert cropped[0].size == (10, 10)
        assert cropped[1].size == (10, 10)

    def test_bbox_alpha_threshold_no_visible(self, svc):
        from PIL import Image
        f = Image.new("RGBA", (5, 5), (0, 0, 0, 0))
        # All alpha=0 -> below threshold -> None.
        assert svc._get_bbox_with_alpha_threshold(f, alpha_threshold=10) is None

    def test_bbox_alpha_threshold_finds_weak_pixel(self, svc):
        from PIL import Image
        f = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        f.putpixel((3, 4), (10, 20, 30, 50))  # alpha=50 > threshold=10
        bbox = svc._get_bbox_with_alpha_threshold(f, alpha_threshold=10)
        assert bbox == (3, 4, 4, 5)

    def test_bbox_alpha_threshold_non_rgba_fallback(self, svc):
        from PIL import Image
        f = Image.new("RGB", (4, 4), (200, 100, 50))
        # RGB image -> falls back to standard getbbox.
        bbox = svc._get_bbox_with_alpha_threshold(f, alpha_threshold=10)
        # All-opaque RGB -> bbox covers full image
        assert bbox == (0, 0, 4, 4)


# ===========================================================================
# 20. _get_actual_mech_folder + _get_actual_mech_folder_no_cache_check
# ===========================================================================
class TestGetActualMechFolder:
    def test_no_cache_check_raises_when_assets_none(self, svc):
        svc.assets_dir = None
        with pytest.raises(FileNotFoundError):
            svc._get_actual_mech_folder_no_cache_check(5)

    def test_no_cache_check_finds_existing_folder(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "Mech7").mkdir()
        result = svc._get_actual_mech_folder_no_cache_check(7)
        assert result.name == "Mech7"

    def test_no_cache_check_falls_back_to_mech1(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "Mech1").mkdir()
        # Asking for Mech9 -> not present -> falls back to Mech1.
        result = svc._get_actual_mech_folder_no_cache_check(9)
        assert result.name == "Mech1"

    def test_no_cache_check_raises_when_mech1_missing_too(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        # Empty assets_dir
        with pytest.raises(FileNotFoundError):
            svc._get_actual_mech_folder_no_cache_check(5)

    def test_actual_mech_folder_uses_cache_virtual_path(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        # Cache exists -> virtual path returned (does NOT need to exist).
        (tmp_path / "mech_3_100speed.cache").write_bytes(b"x")
        result = svc._get_actual_mech_folder(3, "small")
        assert result == tmp_path / "Mech3" / "small"

    def test_actual_mech_folder_big_virtual_path(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "mech_3_100speed.cache").write_bytes(b"x")
        result = svc._get_actual_mech_folder(3, "big")
        assert result == tmp_path / "Mech3" / "big"

    def test_actual_mech_folder_small_subfolder_exists(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "Mech4" / "small").mkdir(parents=True)
        result = svc._get_actual_mech_folder(4, "small")
        assert result.name == "small"
        assert result.parent.name == "Mech4"

    def test_actual_mech_folder_big_falls_back_to_small(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "Mech4").mkdir()
        # Neither big nor small subfolder exists -> falls back to small path.
        result = svc._get_actual_mech_folder(4, "big")
        assert result.name == "small"

    def test_actual_mech_folder_no_subfolder_returns_base(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "Mech4").mkdir()
        # No "small" subfolder -> returns base path itself.
        result = svc._get_actual_mech_folder(4, "small")
        assert result == tmp_path / "Mech4"


# ===========================================================================
# 21. get_cached_animation_path: folder fallback branch
# ===========================================================================
class TestCachedAnimationPathFallback:
    def test_folder_lookup_fallback_uses_actual_level(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        # No cache file exists, but Mech7 folder exists -> filename uses 7.
        (tmp_path / "Mech7").mkdir()
        path = svc.get_cached_animation_path(7, "walk", "small")
        assert path.name == "mech_7_100speed.cache"

    def test_folder_lookup_fallback_falls_back_to_mech1(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "Mech1").mkdir()
        # Asking for Mech9 -> falls back to Mech1 -> filename uses 1.
        path = svc.get_cached_animation_path(9, "walk", "small")
        assert path.name == "mech_1_100speed.cache"


# ===========================================================================
# 22. pre_generate_animation full flow (with mocked frames + WebP creator)
# ===========================================================================
class TestPreGenerateAnimationFlow:
    def test_pre_generate_creates_obfuscated_cache(self, svc, tmp_path):
        # Make assets_dir exist so we don't hit the "no PNG sources" early
        # return.
        svc.assets_dir = tmp_path
        from PIL import Image
        fake_frames = [Image.new("RGBA", (4, 4), (0, 0, 0, 255)) for _ in range(2)]

        with patch.object(svc, "_load_and_process_frames",
                          return_value=fake_frames), \
             patch.object(svc, "_create_unified_webp",
                          return_value=b"FAKE_WEBP_RAW"):
            svc.pre_generate_animation(5, "walk", "small")

        cache_path = svc.get_cached_animation_path(5, "walk", "small")
        assert cache_path.exists()
        # Stored data is obfuscated; deobfuscate and verify.
        on_disk = cache_path.read_bytes()
        assert svc._deobfuscate_data(on_disk) == b"FAKE_WEBP_RAW"

    def test_pre_generate_swallows_io_error(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        with patch.object(svc, "_load_and_process_frames",
                          side_effect=IOError("disk gone")):
            # Must NOT raise.
            svc.pre_generate_animation(5, "walk", "small")

    def test_pre_generate_swallows_value_error(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        with patch.object(svc, "_load_and_process_frames",
                          side_effect=ValueError("frame issue")):
            svc.pre_generate_animation(5, "walk", "small")

    def test_pre_generate_all_animations_iterates_levels(self, svc, tmp_path):
        # assets_dir contains Mech1, Mech4, MechFoo (skipped due to ValueError)
        svc.assets_dir = tmp_path
        (tmp_path / "Mech1").mkdir()
        (tmp_path / "Mech4").mkdir()
        (tmp_path / "MechFoo").mkdir()  # invalid -> skipped
        (tmp_path / "RandomDir").mkdir()  # not Mech-prefixed -> skipped

        called = []
        def fake_pre_gen(level, animation_type="walk", resolution="small"):
            called.append((level, animation_type, resolution))

        with patch.object(svc, "pre_generate_animation",
                          side_effect=fake_pre_gen):
            svc.pre_generate_all_animations()
        # Expect calls for level 1 and 4 (sorted), with type=walk
        assert (1, "walk", "small") in called
        assert (4, "walk", "small") in called

    def test_pre_generate_all_rest_skips_high_levels(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        for n in (1, 5, 11):
            (tmp_path / f"Mech{n}").mkdir()

        called_levels = []
        def fake_pre_rest(level):
            called_levels.append(level)

        with patch.object(svc, "pre_generate_rest_animation",
                          side_effect=fake_pre_rest):
            svc.pre_generate_all_rest_animations()
        # Level 11+ excluded.
        assert 11 not in called_levels
        assert 1 in called_levels and 5 in called_levels

    def test_pre_generate_all_big_filters_for_big_subfolder(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "Mech1" / "big").mkdir(parents=True)
        (tmp_path / "Mech2").mkdir()  # no big subfolder -> skipped

        called = []
        def fake_pre_gen_big(level, animation_type="walk"):
            called.append((level, animation_type))

        with patch.object(svc, "pre_generate_big_animation",
                          side_effect=fake_pre_gen_big):
            svc.pre_generate_all_big_animations()
        # Only level 1 has a big folder.
        assert any(c[0] == 1 for c in called)
        assert not any(c[0] == 2 for c in called)

    def test_pre_generate_all_unified_calls_three(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        with patch.object(svc, "pre_generate_all_animations") as a, \
             patch.object(svc, "pre_generate_all_rest_animations") as r, \
             patch.object(svc, "pre_generate_all_big_animations") as b:
            svc.pre_generate_all_unified_animations()
        a.assert_called_once()
        r.assert_called_once()
        b.assert_called_once()


# ===========================================================================
# 23. Event listener wiring (success + failure)
# ===========================================================================
class TestEventListenerSetup:
    def test_setup_event_listeners_registers_two_handlers(self, tmp_path):
        # Don't stub _setup_event_listeners here — exercise it directly.
        fake_em = MagicMock()
        with patch(
            "services.infrastructure.event_manager.get_event_manager",
            return_value=fake_em,
        ), patch.object(
            AnimationCacheService,
            "enforce_disk_cache_limit",
            lambda self, *a, **kw: 0,
        ), patch.dict(os.environ, {"DDC_ANIM_DISK_LIMIT_MB": "0"}):
            svc = AnimationCacheService()
        # Two register_listener calls expected.
        assert fake_em.register_listener.call_count == 2

    def test_setup_event_listeners_swallows_import_error(self, tmp_path):
        with patch(
            "services.infrastructure.event_manager.get_event_manager",
            side_effect=ImportError("event manager unavailable"),
        ), patch.object(
            AnimationCacheService,
            "enforce_disk_cache_limit",
            lambda self, *a, **kw: 0,
        ), patch.dict(os.environ, {"DDC_ANIM_DISK_LIMIT_MB": "0"}):
            # Construction must succeed despite the failure.
            svc = AnimationCacheService()
        assert svc is not None


# ===========================================================================
# 24. Warmup methods (initial + sync) with fully-stubbed dependencies
# ===========================================================================
class TestWarmupMethods:
    def _stub_data_store(self, level, power, success=True):
        ds = MagicMock()
        result = SimpleNamespace(
            success=success,
            current_level=level,
            current_power=power,
        )
        ds.get_comprehensive_data.return_value = result
        return ds

    def test_perform_sync_cache_warmup_calls_animation_methods(self, svc):
        ds = self._stub_data_store(level=5, power=2.0)
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=ds,
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            return_value={"speed": {"level": 50}},
        ), patch.object(
            svc, "get_animation_with_speed_and_power"
        ) as small, patch.object(
            svc, "get_animation_with_speed_and_power_big"
        ) as big:
            svc._perform_sync_cache_warmup()

        # walk + rest -> small called twice, big called twice.
        assert small.call_count == 2
        assert big.call_count == 2

    def test_perform_sync_cache_warmup_level_11_uses_max_speed(self, svc):
        ds = self._stub_data_store(level=11, power=99.0)
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=ds,
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            side_effect=AssertionError("must not be called for level 11"),
        ), patch.object(
            svc, "get_animation_with_speed_and_power"
        ) as small, patch.object(
            svc, "get_animation_with_speed_and_power_big"
        ) as big:
            svc._perform_sync_cache_warmup()

        # Level 11 only walks (no rest) -> 1 small + 1 big call.
        assert small.call_count == 1
        assert big.call_count == 1
        # Speed must be 100.
        assert small.call_args[0][1] == 100

    def test_perform_sync_cache_warmup_aborts_when_data_missing(self, svc):
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(success=False)
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=ds,
        ), patch.object(
            svc, "get_animation_with_speed_and_power",
            side_effect=AssertionError("should not run"),
        ):
            svc._perform_sync_cache_warmup()

    def test_perform_sync_cache_warmup_handles_import_error(self, svc):
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            side_effect=ImportError("missing module"),
        ):
            # Must not raise.
            svc._perform_sync_cache_warmup()

    @pytest.mark.asyncio
    async def test_perform_initial_cache_warmup_async(self, svc):
        ds = self._stub_data_store(level=4, power=3.0)
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=ds,
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            return_value={"speed": {"level": 30}},
        ), patch.object(
            svc, "get_animation_with_speed_and_power"
        ) as small, patch.object(
            svc, "get_animation_with_speed_and_power_big"
        ) as big:
            await svc.perform_initial_cache_warmup()
        # walk + rest both small + big = 4 total
        assert small.call_count == 2
        assert big.call_count == 2

    @pytest.mark.asyncio
    async def test_perform_initial_cache_warmup_data_unavailable(self, svc):
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(success=False)
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=ds,
        ):
            await svc.perform_initial_cache_warmup()

    def test_sync_recache_current_animations(self, svc):
        with patch.object(
            svc, "_perform_service_first_sync_warmup"
        ) as inner:
            svc._sync_recache_current_animations(reason="x")
        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_recache_current_animations(self, svc):
        from unittest.mock import AsyncMock
        with patch.object(
            svc, "_perform_service_first_async_warmup",
            new=AsyncMock(return_value=None),
        ):
            await svc._async_recache_current_animations(reason="x")

    def test_perform_service_first_sync_warmup_uses_web_service(self, svc):
        """Exercise the SERVICE FIRST sync warmup happy path."""
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(
            success=True, current_power=10.0,
        )
        web_svc = MagicMock()
        web_svc.get_live_animation.return_value = SimpleNamespace(
            success=True, animation_bytes=b"WEB", error=None,
        )

        # Patch on the source modules where these accessors live.
        import services.web.mech_web_service as mws
        import services.mech.mech_data_store as mds

        with patch.object(mws, "get_mech_web_service", return_value=web_svc), \
             patch.object(mds, "get_mech_data_store", return_value=ds):
            svc._perform_service_first_sync_warmup()
        # Two resolutions -> two get_live_animation calls.
        assert web_svc.get_live_animation.call_count == 2

    def test_perform_service_first_sync_warmup_data_unavailable(self, svc):
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(success=False)
        web_svc = MagicMock()

        import services.web.mech_web_service as mws
        import services.mech.mech_data_store as mds

        with patch.object(mws, "get_mech_web_service", return_value=web_svc), \
             patch.object(mds, "get_mech_data_store", return_value=ds):
            svc._perform_service_first_sync_warmup()
        # Should NOT have called the web service when data store fails.
        web_svc.get_live_animation.assert_not_called()

    @pytest.mark.asyncio
    async def test_perform_service_first_async_warmup_happy_path(self, svc):
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(
            success=True, current_power=4.0,
        )
        web_svc = MagicMock()
        web_svc.get_live_animation.return_value = SimpleNamespace(
            success=True, animation_bytes=b"OK", error=None,
        )

        import services.web.mech_web_service as mws
        import services.mech.mech_data_store as mds

        with patch.object(mws, "get_mech_web_service", return_value=web_svc), \
             patch.object(mds, "get_mech_data_store", return_value=ds):
            await svc._perform_service_first_async_warmup()
        assert web_svc.get_live_animation.call_count == 2

    @pytest.mark.asyncio
    async def test_perform_service_first_async_warmup_data_unavailable(self, svc):
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(success=False)
        web_svc = MagicMock()

        import services.web.mech_web_service as mws
        import services.mech.mech_data_store as mds

        with patch.object(mws, "get_mech_web_service", return_value=web_svc), \
             patch.object(mds, "get_mech_data_store", return_value=ds):
            await svc._perform_service_first_async_warmup()
        web_svc.get_live_animation.assert_not_called()

    @pytest.mark.asyncio
    async def test_perform_service_first_async_warmup_failure_logs(self, svc):
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(
            success=True, current_power=4.0,
        )
        web_svc = MagicMock()
        # web_service raises -> should be caught per-resolution.
        web_svc.get_live_animation.side_effect = ValueError("bad request")

        import services.web.mech_web_service as mws
        import services.mech.mech_data_store as mds

        with patch.object(mws, "get_mech_web_service", return_value=web_svc), \
             patch.object(mds, "get_mech_data_store", return_value=ds):
            await svc._perform_service_first_async_warmup()
        # Both resolutions tried (and both errored, but were swallowed).
        assert web_svc.get_live_animation.call_count == 2

    def test_perform_service_first_sync_warmup_failure_logs(self, svc):
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(
            success=True, current_power=2.0,
        )
        web_svc = MagicMock()
        web_svc.get_live_animation.side_effect = ValueError("bad request")

        import services.web.mech_web_service as mws
        import services.mech.mech_data_store as mds

        with patch.object(mws, "get_mech_web_service", return_value=web_svc), \
             patch.object(mds, "get_mech_data_store", return_value=ds):
            svc._perform_service_first_sync_warmup()
        assert web_svc.get_live_animation.call_count == 2

    def test_perform_service_first_sync_warmup_returns_failed_result(self, svc):
        ds = MagicMock()
        ds.get_comprehensive_data.return_value = SimpleNamespace(
            success=True, current_power=2.0,
        )
        web_svc = MagicMock()
        web_svc.get_live_animation.return_value = SimpleNamespace(
            success=False, animation_bytes=None, error="boom",
        )

        import services.web.mech_web_service as mws
        import services.mech.mech_data_store as mds

        with patch.object(mws, "get_mech_web_service", return_value=web_svc), \
             patch.object(mds, "get_mech_data_store", return_value=ds):
            svc._perform_service_first_sync_warmup()

    def test_perform_service_first_sync_warmup_handles_import_error(self, svc):
        import services.web.mech_web_service as mws
        with patch.object(
            mws, "get_mech_web_service", side_effect=ImportError("missing"),
        ):
            svc._perform_service_first_sync_warmup()


# ===========================================================================
# 25. Event handler async-path branch (running event loop)
# ===========================================================================
class TestEventHandlersAsyncBranch:
    @pytest.mark.asyncio
    async def test_donation_event_with_running_loop_creates_task(self, svc):
        from unittest.mock import AsyncMock
        svc._store_in_ram_cache("k", b"v")
        event_data = SimpleNamespace(data={"amount": "10"})

        async_mock = AsyncMock(return_value=None)
        with patch.object(
            svc, "_async_recache_current_animations", new=async_mock,
        ), patch.object(
            svc, "_sync_recache_current_animations",
            side_effect=AssertionError("must use async path"),
        ):
            svc._handle_donation_event(event_data)

        # Cache should be cleared.
        assert len(svc._focused_cache) == 0
        # Async path should have been invoked (called once via create_task).
        async_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_state_change_event_with_running_loop_creates_task(self, svc):
        from unittest.mock import AsyncMock
        svc._store_in_ram_cache("k", b"v")
        event = SimpleNamespace(data={"old_power": 0.0, "new_power": 5.0})

        async_mock = AsyncMock(return_value=None)
        with patch.object(
            svc, "_async_recache_current_animations", new=async_mock,
        ), patch.object(
            svc, "_sync_recache_current_animations",
            side_effect=AssertionError("must use async path"),
        ):
            svc._handle_state_change_event(event)

        assert len(svc._focused_cache) == 0
        async_mock.assert_called_once()


# ===========================================================================
# 26. _get_animation_internal: speed-cache file read fails -> regen path
# ===========================================================================
class TestSpeedCacheReadError:
    def test_speed_cache_open_failure_falls_through_to_regen(self, svc, tmp_path):
        # Set up a base cache so the regen step succeeds.
        base = svc.get_cached_animation_path(5, "walk", "small")
        base.write_bytes(svc._obfuscate_data(b"BASE"))
        # Place a speed-cache file (so the disk-cache branch executes), but
        # patch open() to raise ONLY for that file.
        speed_path = tmp_path / "mech_L5_walk_small_S80.webp"
        speed_path.write_bytes(b"GARBAGE")

        real_open = open

        def selective_open(path, *args, **kwargs):
            if str(path).endswith("S80.webp") and "rb" in args:
                raise IOError("transient read fail")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=selective_open):
            with patch.object(svc, "_apply_speed_to_animation",
                              return_value=b"REGEN"):
                out = svc._get_animation_internal(5, 80, 1.0, "small")

        # Falls through to regen, which uses _apply_speed_to_animation.
        assert out == b"REGEN"


# ===========================================================================
# 28. _load_and_process_frames using REAL on-disk PNGs
# ===========================================================================
def _write_walk_pngs(folder: Path, level: int, n: int = 3, size=(64, 64)) -> None:
    """Write a small sequence of walk PNG frames to ``folder``."""
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        # Put a small visible region for cropping to find content.
        for x in range(10, 20):
            for y in range(10, 20):
                img.putpixel((x, y), (255, 255, 255, 255))
        img.save(folder / f"{level}_walk_{i:04d}.png", format="PNG")


def _write_rest_pngs(folder: Path, level: int, n: int = 2, size=(64, 200)) -> None:
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        for x in range(20, 30):
            for y in range(80, 100):
                img.putpixel((x, y), (200, 100, 50, 255))
        img.save(folder / f"{level}_rest_{i:04d}.png", format="PNG")


class TestLoadAndProcessFrames:
    def test_no_pngs_raises(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        # Mech1 folder exists but has no PNGs that match the pattern.
        (tmp_path / "Mech1" / "small").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            svc._load_and_process_frames(1, "walk", "small")

    def test_walk_level_1_returns_frames(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_walk_pngs(tmp_path / "Mech1" / "small", level=1, n=2)
        frames = svc._load_and_process_frames(1, "walk", "small")
        assert len(frames) == 2

    def test_walk_level_4_pre_crop_branch(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        # Level 4 takes a special pre-crop path.
        _write_walk_pngs(tmp_path / "Mech4" / "small", level=4, n=2, size=(64, 64))
        frames = svc._load_and_process_frames(4, "walk", "small")
        assert len(frames) == 2

    def test_walk_level_5_pre_crop_branch(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_walk_pngs(tmp_path / "Mech5" / "small", level=5, n=2, size=(64, 64))
        frames = svc._load_and_process_frames(5, "walk", "small")
        assert len(frames) == 2

    def test_walk_level_6_pre_crop_branch(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_walk_pngs(tmp_path / "Mech6" / "small", level=6, n=2, size=(96, 96))
        frames = svc._load_and_process_frames(6, "walk", "small")
        assert len(frames) == 2

    def test_walk_level_10_small_pre_crop(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_walk_pngs(tmp_path / "Mech10" / "small", level=10, n=2,
                         size=(128, 128))
        frames = svc._load_and_process_frames(10, "walk", "small")
        assert len(frames) == 2

    def test_walk_level_10_big_no_crop(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_walk_pngs(tmp_path / "Mech10" / "big", level=10, n=2,
                         size=(412, 412))
        frames = svc._load_and_process_frames(10, "walk", "big")
        # Bypass branch returns frames unchanged at original resolution.
        assert len(frames) == 2
        assert frames[0].size == (412, 412)

    def test_rest_level_3_small_with_crop(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_rest_pngs(tmp_path / "Mech3" / "small", level=3, n=2,
                         size=(64, 200))
        frames = svc._load_and_process_frames(3, "rest", "small")
        assert len(frames) == 2

    def test_rest_level_4_small_uses_alpha_threshold(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        # Level 4 + rest + small triggers _get_bbox_with_alpha_threshold path.
        _write_rest_pngs(tmp_path / "Mech4" / "small", level=4, n=2,
                         size=(64, 200))
        frames = svc._load_and_process_frames(4, "rest", "small")
        assert len(frames) == 2

    def test_rest_level_5_big_proportional_crop(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        # Big rest goes through proportional crop branch.
        _write_rest_pngs(tmp_path / "Mech5" / "big", level=5, n=2,
                         size=(128, 400))
        frames = svc._load_and_process_frames(5, "rest", "big")
        assert len(frames) == 2

    def test_walk_no_visible_content_fallback(self, svc, tmp_path):
        from PIL import Image
        svc.assets_dir = tmp_path
        folder = tmp_path / "Mech1" / "small"
        folder.mkdir(parents=True)
        # All-transparent frames -> bbox=None -> fallback path.
        for i in range(2):
            img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
            img.save(folder / f"1_walk_{i:04d}.png", format="PNG")
        frames = svc._load_and_process_frames(1, "walk", "small")
        # Fallback returns frames as-is (no crop, since min_x stayed inf).
        assert len(frames) == 2


# ===========================================================================
# 29. _get_walk_scale_factor (uses REAL PNGs)
# ===========================================================================
class TestWalkScaleFactor:
    def test_returns_one_for_present_walk_pngs(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_walk_pngs(tmp_path / "Mech3" / "small", level=3, n=3,
                         size=(64, 64))
        # First call computes & caches.
        sf = svc._get_walk_scale_factor(3)
        assert sf == 1.0
        assert svc._walk_scale_factors[3] == 1.0
        # Second call hits cache.
        assert svc._get_walk_scale_factor(3) == 1.0

    def test_returns_one_for_level_8_pattern(self, svc, tmp_path):
        from PIL import Image
        svc.assets_dir = tmp_path
        # Level 8 uses different glob pattern: 8_XXXX.png (no "walk").
        folder = tmp_path / "Mech8" / "small"
        folder.mkdir(parents=True)
        for i in range(3):
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            for x in range(20, 30):
                for y in range(20, 30):
                    img.putpixel((x, y), (255, 255, 255, 255))
            img.save(folder / f"8_{i:04d}.png", format="PNG")
        sf = svc._get_walk_scale_factor(8)
        assert sf == 1.0

    def test_no_files_returns_one_and_caches(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        (tmp_path / "Mech7" / "small").mkdir(parents=True)
        # No PNGs at all -> warning + fallback 1.0
        assert svc._get_walk_scale_factor(7) == 1.0
        assert svc._walk_scale_factors[7] == 1.0

    def test_level_4_has_pre_crop_in_scale_factor(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        # Level 4 triggers a pre-crop branch (line ~333).
        _write_walk_pngs(tmp_path / "Mech4" / "small", level=4, n=3,
                         size=(64, 64))
        assert svc._get_walk_scale_factor(4) == 1.0

    def test_level_5_pre_crop_in_scale_factor(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_walk_pngs(tmp_path / "Mech5" / "small", level=5, n=3,
                         size=(64, 64))
        assert svc._get_walk_scale_factor(5) == 1.0

    def test_level_6_pre_crop_in_scale_factor(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        _write_walk_pngs(tmp_path / "Mech6" / "small", level=6, n=3,
                         size=(96, 96))
        assert svc._get_walk_scale_factor(6) == 1.0

    def test_no_visible_content_returns_one(self, svc, tmp_path):
        from PIL import Image
        svc.assets_dir = tmp_path
        folder = tmp_path / "Mech2" / "small"
        folder.mkdir(parents=True)
        # All-transparent walks -> getbbox() returns None -> fallback.
        for i in range(3):
            img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
            img.save(folder / f"2_walk_{i:04d}.png", format="PNG")
        assert svc._get_walk_scale_factor(2) == 1.0

    def test_io_error_returns_one(self, svc, tmp_path):
        svc.assets_dir = tmp_path
        with patch.object(svc, "_get_actual_mech_folder",
                          side_effect=OSError("disk failed")):
            assert svc._get_walk_scale_factor(3) == 1.0


# ===========================================================================
# 30. _get_animation_internal: regen-write disk-cache failure swallowed
# ===========================================================================
class TestRegenWriteFailureSwallowed:
    def test_regen_path_continues_when_disk_write_fails(self, svc, tmp_path):
        base = svc.get_cached_animation_path(5, "walk", "small")
        base.write_bytes(svc._obfuscate_data(b"BASE"))

        adjusted = b"ADJUSTED"
        real_open = open

        # Make writing the speed cache fail; reading still works.
        def fail_writes(path, mode="r", *args, **kwargs):
            if "w" in mode and "S80.webp" in str(path):
                raise IOError("write protected")
            return real_open(path, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=fail_writes):
            with patch.object(
                svc, "_apply_speed_to_animation", return_value=adjusted,
            ):
                out = svc._get_animation_internal(5, 80, 1.0, "small")

        assert out == adjusted
        # Speed file should NOT exist (write failed).
        speed_path = tmp_path / "mech_L5_walk_small_S80.webp"
        assert not speed_path.exists()
