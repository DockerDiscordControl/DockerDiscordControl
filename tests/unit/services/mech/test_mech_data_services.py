# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Data Services Unit Tests                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Functional unit tests for the four mech-data services:

* services.mech.mech_data_store
* services.mech.mech_status_cache_service
* services.mech.mech_reset_service
* services.mech.mech_state_manager

Strategy
--------
* Heavy collaborators (progress_service, mech_service, mech_evolutions,
  speed_levels, unified_donation_service, event_manager, config_service) are
  patched on a per-test basis with ``unittest.mock.patch`` — we never touch
  ``sys.modules``.
* JSON state files are written to ``tmp_path``.  ``MechResetService`` is
  pointed at a temporary config dir; ``MechStateManager`` is constructed
  with an explicit state-file path.  ``MechStatusCacheService`` is built
  through its constructor while ``get_event_manager`` is patched so that
  the listener registration never reaches the production singleton.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from services.mech import mech_data_store as mds_module
from services.mech.mech_data_store import (
    BarsCompat,
    DecayDataRequest,
    EvolutionDataRequest,
    LevelDataRequest,
    MechDataRequest,
    MechDataResult,
    MechDataStore,
    PowerDataRequest,
    ProjectionDataRequest,
    SpeedDataRequest,
    get_mech_data_store,
)
from services.mech import mech_status_cache_service as mscs_module
from services.mech.mech_status_cache_service import (
    MechStatusCacheRequest,
    MechStatusCacheResult,
    MechStatusCacheService,
    get_mech_status_cache_service,
)
from services.mech import mech_reset_service as mrs_module
from services.mech.mech_reset_service import (
    MechResetService,
    ResetResult,
    get_mech_reset_service,
    quick_mech_reset,
)
from services.mech.mech_state_manager import (
    MechStateManager,
    get_mech_state_manager,
)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------
def _build_mech_state_result(level=3, power=42.5, total_donated=125.0):
    """Create a stand-in for MechStateServiceResult."""
    return SimpleNamespace(
        success=True,
        level=level,
        power=power,
        total_donated=total_donated,
        name=f"Level {level}",
        threshold=200.0,
        speed=85.0,
        error=None,
    )


def _build_progress_state(level=3, power_current=42.5, power_max=100.0,
                          evo_current=10.0, evo_max=20.0, total_donated=125.0,
                          is_offline=False):
    """Stand-in for ProgressState."""
    return SimpleNamespace(
        level=level,
        power_current=power_current,
        power_max=power_max,
        power_percent=int(power_current / power_max * 100) if power_max else 0,
        evo_current=evo_current,
        evo_max=evo_max,
        evo_percent=int(evo_current / evo_max * 100) if evo_max else 0,
        total_donated=total_donated,
        can_level_up=False,
        is_offline=is_offline,
        difficulty_bin=1,
        difficulty_tier="medium",
        member_count=10,
    )


def _build_combined_status(level=2, description="WALK", color="#11ff11"):
    """Stand-in for speed_levels.get_combined_mech_status output."""
    return {
        "speed": {
            "level": level,
            "description": description,
            "color": color,
        }
    }


def _build_evolution_info(name="Walker", decay_per_day=2.4):
    """Stand-in for EvolutionLevelInfo."""
    return SimpleNamespace(name=name, decay_per_day=decay_per_day)


# ---------------------------------------------------------------------------
# Singleton reset fixture (autouse) — keeps tests independent
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_mech_singletons():
    mds_module._mech_data_store_instance = None
    mscs_module._mech_status_cache_service = None
    mrs_module._mech_reset_service = None
    yield
    mds_module._mech_data_store_instance = None
    mscs_module._mech_status_cache_service = None
    mrs_module._mech_reset_service = None


# ===========================================================================
#                          mech_data_store tests
# ===========================================================================
class TestMechDataStoreCaching:
    """Cache TTL, store, retrieve, manual clear, cleanup."""

    def test_singleton_returns_same_instance(self):
        a = get_mech_data_store()
        b = get_mech_data_store()
        assert a is b
        assert isinstance(a, MechDataStore)

    def test_store_and_retrieve_from_cache(self):
        store = MechDataStore()
        result = MechDataResult(success=True, current_level=5)
        store._store_in_cache("key1", result)

        cached = store._get_from_cache("key1")
        assert cached is result

    def test_get_from_cache_returns_none_for_missing_key(self):
        store = MechDataStore()
        assert store._get_from_cache("does-not-exist") is None

    def test_cache_expires_after_ttl(self):
        store = MechDataStore()
        store._cache_ttl = 0.0  # immediate expiry
        store._store_in_cache("key1", MechDataResult(success=True))
        # With TTL = 0, any positive elapsed time invalidates.
        time.sleep(0.001)
        assert store._get_from_cache("key1") is None
        # Expired entry was removed from internal dict.
        assert "key1" not in store._cache

    def test_clear_cache_empties_storage(self):
        store = MechDataStore()
        store._store_in_cache("key1", MechDataResult(success=True))
        store._store_in_cache("key2", MechDataResult(success=True))
        assert len(store._cache) == 2

        store.clear_cache()
        assert store._cache == {}

    def test_cleanup_cache_removes_only_expired(self):
        store = MechDataStore()
        store._cache_ttl = 1.0
        store._cache["fresh"] = {
            "data": MechDataResult(success=True),
            "timestamp": time.time(),
        }
        store._cache["stale"] = {
            "data": MechDataResult(success=True),
            "timestamp": time.time() - 10.0,
        }
        store._cleanup_cache()

        assert "fresh" in store._cache
        assert "stale" not in store._cache


class TestMechDataStoreCalculations:
    """Internal _calculate_* helpers (no full pipeline)."""

    def test_calculate_progress_data_uses_evolution_threshold(self):
        store = MechDataStore()
        out = store._calculate_progress_data(
            core_data={"total_donated": 5},
            evolution_data={"next_threshold": 20},
        )
        assert out["progress_max"] == 20
        assert out["progress_current"] == 5
        assert out["progress_percentage"] == pytest.approx(25.0)

    def test_calculate_progress_data_clamps_overflow(self):
        store = MechDataStore()
        out = store._calculate_progress_data(
            core_data={"total_donated": 999},
            evolution_data={"next_threshold": 20},
        )
        assert out["progress_current"] == 20
        assert out["progress_max"] == 20

    def test_calculate_progress_data_max_level_branch(self):
        store = MechDataStore()
        out = store._calculate_progress_data(
            core_data={"total_donated": 99999},
            evolution_data={"next_threshold": 0},
        )
        assert out["progress_percentage"] == 100.0
        assert out["progress_current"] == 100

    def test_calculate_projections_categorises_critical(self):
        store = MechDataStore()
        out = store._calculate_projections(
            core_data={"power": 0.5},
            decay_data={"decay_per_hour": 1.0, "is_immortal": False},
            hours_ahead=24.0,
        )
        assert out["survival_category"] == "critical"
        assert out["projected_power"] == 0.0  # max(0, 0.5 - 24)

    def test_calculate_projections_categorises_healthy(self):
        store = MechDataStore()
        out = store._calculate_projections(
            core_data={"power": 1000.0},
            decay_data={"decay_per_hour": 1.0, "is_immortal": False},
            hours_ahead=24.0,
        )
        assert out["survival_category"] == "healthy"
        assert out["hours_until_zero"] == 1000.0

    def test_calculate_projections_immortal_branch(self):
        store = MechDataStore()
        out = store._calculate_projections(
            core_data={"power": 50.0},
            decay_data={"decay_per_hour": 0.0, "is_immortal": True},
            hours_ahead=12.0,
        )
        assert out["hours_until_zero"] is None
        assert out["survival_category"] == "immortal"

    def test_get_core_mech_data_handles_failed_state(self):
        store = MechDataStore()
        failing_result = SimpleNamespace(success=False, error="boom",
                                         level=0, power=0.0, total_donated=0.0)
        fake_service = MagicMock()
        fake_service.get_mech_state_service.return_value = failing_result
        with patch("services.mech.mech_service.get_mech_service",
                   return_value=fake_service):
            out = store._get_core_mech_data()
        assert out["success"] is False
        assert "boom" in out["error"]

    def test_get_core_mech_data_dependency_error(self):
        store = MechDataStore()
        fake_service = MagicMock()
        fake_service.get_mech_state_service.side_effect = AttributeError("nope")
        with patch("services.mech.mech_service.get_mech_service",
                   return_value=fake_service):
            out = store._get_core_mech_data()
        assert out["success"] is False
        assert "nope" in out["error"]

    def test_calculate_decay_falls_back_when_no_info(self):
        store = MechDataStore()
        with patch("services.mech.mech_evolutions.get_evolution_level_info",
                   return_value=None):
            out = store._calculate_decay_data({"level": 3})
        assert out["decay_rate"] == 1.0
        assert out["is_immortal"] is False

    def test_calculate_decay_immortal_when_decay_zero(self):
        store = MechDataStore()
        with patch("services.mech.mech_evolutions.get_evolution_level_info",
                   return_value=_build_evolution_info(decay_per_day=0.0)):
            out = store._calculate_decay_data({"level": 11})
        assert out["is_immortal"] is True
        assert out["decay_rate"] == 0.0

    def test_calculate_evolution_data_uses_progress_state(self):
        store = MechDataStore()
        prog_state = _build_progress_state(level=4, evo_current=7, evo_max=20)
        fake_progress = MagicMock()
        fake_progress.get_state.return_value = prog_state
        with patch("services.mech.progress_service.get_progress_service",
                   return_value=fake_progress), \
             patch("services.mech.mech_evolutions.get_evolution_level_info",
                   side_effect=lambda lvl: _build_evolution_info(name=f"L{lvl}")):
            out = store._calculate_evolution_data({"level": 4})
        assert out["next_level"] == 5
        assert out["next_threshold"] == 20
        assert out["amount_needed"] == 13
        assert out["level_name"] == "L4"
        assert out["next_level_name"] == "L5"

    def test_calculate_speed_data_returns_offline_fallback_on_import_error(self):
        store = MechDataStore()
        with patch("services.mech.speed_levels.get_combined_mech_status",
                   side_effect=ImportError("missing")):
            out = store._calculate_speed_data({"power": 0.0, "total_donated": 0}, "en")
        assert out["speed_description"] == "OFFLINE"
        assert out["speed_level"] == 0


class TestMechDataStorePipeline:
    """End-to-end (with all collaborators mocked) — ensures aggregation works."""

    def _patch_all(self):
        """Return contextmanagers patching every collaborator at import-site."""
        # Build the standard payloads
        core_state = _build_mech_state_result(level=4, power=50.0,
                                              total_donated=300.0)
        prog_state = _build_progress_state(level=4, power_current=50.0,
                                           power_max=100.0, evo_current=15.0,
                                           evo_max=40.0, total_donated=300.0)
        combined = _build_combined_status(level=3, description="RUN",
                                          color="#22cc22")

        fake_mech_service = MagicMock()
        fake_mech_service.get_mech_state_service.return_value = core_state
        fake_mech_service._get_evolution_mode.return_value = {
            "use_dynamic": True, "difficulty_multiplier": 1.5,
        }
        fake_progress = MagicMock()
        fake_progress.get_state.return_value = prog_state

        return [
            patch("services.mech.mech_service.get_mech_service",
                  return_value=fake_mech_service),
            patch("services.mech.progress_service.get_progress_service",
                  return_value=fake_progress),
            patch("services.mech.mech_evolutions.get_evolution_level_info",
                  side_effect=lambda lvl: _build_evolution_info(
                      name=f"Mech-L{lvl}", decay_per_day=2.4)),
            patch("services.mech.speed_levels.get_combined_mech_status",
                  return_value=combined),
        ]

    def test_get_comprehensive_data_success(self):
        store = MechDataStore()
        with self._patch_all()[0], self._patch_all()[1], \
             self._patch_all()[2], self._patch_all()[3]:
            result = store.get_comprehensive_data(
                MechDataRequest(force_refresh=True))

        assert result.success is True
        assert result.current_level == 4
        assert result.current_power == 50.0
        assert result.total_donated == 300.0
        assert result.level_name == "Mech-L4"
        assert result.next_level_name == "Mech-L5"
        # decay_per_day=2.4 -> per-hour 0.1
        assert result.decay_per_hour == pytest.approx(2.4 / 24.0)
        # Evolution mode passthrough
        assert result.evolution_mode == "dynamic"
        assert result.difficulty_multiplier == 1.5
        # Bars built
        assert isinstance(result.bars, BarsCompat)
        assert result.bars.Power_current == 50.0

    def test_get_comprehensive_data_uses_cache(self):
        store = MechDataStore()
        # First call: prime the cache
        with self._patch_all()[0], self._patch_all()[1], \
             self._patch_all()[2], self._patch_all()[3]:
            first = store.get_comprehensive_data(MechDataRequest())
        assert first.success is True

        # Second call (no force_refresh): mech_service must NOT be hit again.
        sentinel_service = MagicMock(side_effect=AssertionError(
            "mech_service was called despite cache hit"))
        with patch("services.mech.mech_service.get_mech_service",
                   sentinel_service):
            second = store.get_comprehensive_data(MechDataRequest())
        assert second is first  # cache returned the same object

    def test_get_comprehensive_data_propagates_failure(self):
        store = MechDataStore()
        failing = SimpleNamespace(success=False, error="state-bad",
                                  level=0, power=0.0, total_donated=0.0)
        fake = MagicMock()
        fake.get_mech_state_service.return_value = failing
        with patch("services.mech.mech_service.get_mech_service",
                   return_value=fake):
            res = store.get_comprehensive_data(
                MechDataRequest(force_refresh=True))
        assert res.success is False
        assert "state-bad" in (res.error or "")

    def test_get_level_info_proxies_through_comprehensive(self):
        store = MechDataStore()
        with self._patch_all()[0], self._patch_all()[1], \
             self._patch_all()[2], self._patch_all()[3]:
            res = store.get_level_info(LevelDataRequest(force_refresh=True))
        assert res.success is True
        assert res.current_level == 4
        assert res.next_level == 5

    def test_get_power_info_proxies_through_comprehensive(self):
        store = MechDataStore()
        with self._patch_all()[0], self._patch_all()[1], \
             self._patch_all()[2], self._patch_all()[3]:
            res = store.get_power_info(
                PowerDataRequest(include_decimals=True, force_refresh=True))
        assert res.success is True
        assert res.current_power == 50.0

    def test_get_evolution_info_proxies(self):
        store = MechDataStore()
        with self._patch_all()[0], self._patch_all()[1], \
             self._patch_all()[2], self._patch_all()[3]:
            res = store.get_evolution_info(
                EvolutionDataRequest(force_refresh=True, language="en"))
        assert res.success is True
        assert res.evolution_mode == "dynamic"

    def test_get_speed_info_proxies(self):
        store = MechDataStore()
        with self._patch_all()[0], self._patch_all()[1], \
             self._patch_all()[2], self._patch_all()[3]:
            res = store.get_speed_info(
                SpeedDataRequest(force_refresh=True))
        assert res.success is True
        assert res.speed_description == "RUN"
        assert res.speed_color == "#22cc22"

    def test_get_decay_info_calculates_survival_hours(self):
        store = MechDataStore()
        with self._patch_all()[0], self._patch_all()[1], \
             self._patch_all()[2], self._patch_all()[3]:
            res = store.get_decay_info(
                DecayDataRequest(force_refresh=True))
        assert res.success is True
        # power=50, decay_per_hour = 2.4/24 = 0.1
        assert res.survival_hours == pytest.approx(50.0 / (2.4 / 24.0))

    def test_get_projections_includes_data(self):
        store = MechDataStore()
        with self._patch_all()[0], self._patch_all()[1], \
             self._patch_all()[2], self._patch_all()[3]:
            res = store.get_projections(
                ProjectionDataRequest(hours_ahead=12.0, force_refresh=True))
        assert res.success is True
        assert res.projections is not None
        assert "projected_power" in res.projections


# ===========================================================================
#                    mech_status_cache_service tests
# ===========================================================================
class TestMechStatusCacheService:
    """Cache get/set/invalidate, mtime/TTL based expiry, fallback flows."""

    @pytest.fixture
    def service(self):
        # Patch the event-manager so __init__ does not touch the production
        # singleton.
        with patch.object(MechStatusCacheService, "_setup_event_listeners"):
            yield MechStatusCacheService()

    def test_init_calls_event_listener_setup(self):
        with patch.object(MechStatusCacheService, "_setup_event_listeners") as m:
            MechStatusCacheService()
        m.assert_called_once()

    def test_singleton_factory_returns_same_instance(self):
        with patch.object(MechStatusCacheService, "_setup_event_listeners"):
            a = get_mech_status_cache_service()
            b = get_mech_status_cache_service()
        assert a is b

    def test_store_and_retrieve_from_cache(self, service):
        result = MechStatusCacheResult(success=True, level=5, power=12.5)
        service._store_in_cache(result, include_decimals=False)

        cached = service._get_from_cache(False)
        assert cached is not None
        assert cached.level == 5
        assert cached.cache_age_seconds >= 0

    def test_cache_get_misses_when_empty(self, service):
        assert service._get_from_cache(False) is None

    def test_cache_expires_after_ttl(self, service):
        service._cache_ttl = 0.01
        service._store_in_cache(
            MechStatusCacheResult(success=True), include_decimals=False)
        time.sleep(0.05)
        assert service._get_from_cache(False) is None

    def test_clear_cache_empties_storage(self, service):
        service._store_in_cache(MechStatusCacheResult(success=True), False)
        service._store_in_cache(MechStatusCacheResult(success=True), True)
        assert len(service._cache) == 2
        service.clear_cache()
        assert service._cache == {}

    def test_get_cached_status_cache_hit(self, service):
        result = MechStatusCacheResult(success=True, level=7)
        service._store_in_cache(result, include_decimals=False)

        out = service.get_cached_status(MechStatusCacheRequest(
            include_decimals=False, force_refresh=False))
        assert out.level == 7
        assert out.success is True

    def test_get_cached_status_cache_miss_calls_fetch(self, service):
        fresh = MechStatusCacheResult(success=True, level=9, power=33.0)
        with patch.object(service, "_fetch_fresh_status",
                          return_value=fresh) as fetch:
            out = service.get_cached_status(MechStatusCacheRequest(
                include_decimals=False, force_refresh=False))

        fetch.assert_called_once_with(False)
        assert out.level == 9
        # And it has been stored.
        assert service._get_from_cache(False) is not None

    def test_get_cached_status_force_refresh_bypasses_cache(self, service):
        service._store_in_cache(
            MechStatusCacheResult(success=True, level=1), False)
        fresh = MechStatusCacheResult(success=True, level=99)
        with patch.object(service, "_fetch_fresh_status", return_value=fresh):
            out = service.get_cached_status(MechStatusCacheRequest(
                force_refresh=True))
        assert out.level == 99

    def test_get_cached_status_handles_fetch_exception(self, service):
        with patch.object(service, "_fetch_fresh_status",
                          side_effect=ImportError("no module")):
            out = service.get_cached_status(MechStatusCacheRequest())
        assert out.success is False
        assert "Service dependency error" in (out.error_message or "")

    def test_fetch_fresh_status_builds_result_from_data_store(self, service):
        # Build a fake comprehensive_data result.
        fake_data_result = MechDataResult(
            success=True,
            current_level=6,
            current_power=18.0,
            total_donated=150.0,
            level_name="Runner",
            next_level_threshold=100.0,
            bars=BarsCompat(Power_current=18.0, Power_max_for_level=50),
        )
        fake_data_store = MagicMock()
        fake_data_store.get_comprehensive_data.return_value = fake_data_result

        # Config service: makes language fall through to fallback ('de').
        fake_config_service = MagicMock()
        fake_config_service.get_config_service.side_effect = AttributeError("no")

        with patch("services.mech.mech_data_store.get_mech_data_store",
                   return_value=fake_data_store), \
             patch("services.config.config_service.get_config_service",
                   return_value=fake_config_service), \
             patch("services.mech.speed_levels.get_combined_mech_status",
                   return_value=_build_combined_status(
                       level=2, description="WALK", color="#aaa")):
            out = service._fetch_fresh_status(False)

        assert out.success is True
        assert out.level == 6
        assert out.power == 18.0
        assert out.name == "Runner"
        assert out.threshold == 100
        assert out.speed_description == "WALK"
        assert out.bars is not None

    def test_fetch_fresh_status_failure_when_data_store_fails(self, service):
        bad = MechDataResult(success=False, error="store-broken")
        fake_data_store = MagicMock()
        fake_data_store.get_comprehensive_data.return_value = bad

        fake_config_service = MagicMock()
        config_result = SimpleNamespace(
            success=True, config={"language": "en"})
        fake_config_service.get_config_service.return_value = config_result

        with patch("services.mech.mech_data_store.get_mech_data_store",
                   return_value=fake_data_store), \
             patch("services.config.config_service.get_config_service",
                   return_value=fake_config_service):
            out = service._fetch_fresh_status(False)
        assert out.success is False
        assert "Failed" in out.error_message

    def test_fetch_fresh_status_handles_data_error(self, service):
        # Data store raises a ValueError → maps to data-processing error.
        with patch("services.mech.mech_data_store.get_mech_data_store",
                   side_effect=ValueError("bad value")), \
             patch("services.config.config_service.get_config_service",
                   side_effect=ImportError("missing")):
            out = service._fetch_fresh_status(False)
        assert out.success is False

    def test_get_cache_stats_returns_metadata(self, service):
        service._store_in_cache(MechStatusCacheResult(success=True), False)
        stats = service.get_cache_stats()
        assert stats["entries"] == 1
        assert stats["ttl_seconds"] == service._cache_ttl
        assert stats["loop_running"] is False
        assert "entries_detail" in stats
        # The single entry should be present in the detail dict.
        assert any("mech_status" in k for k in stats["entries_detail"])

    def test_handle_donation_event_clears_cache(self, service):
        service._store_in_cache(MechStatusCacheResult(success=True), False)
        evt = SimpleNamespace(
            data={"amount": 12.5},
            source_service="donation",
        )

        # Patch event_manager used inside _handle_donation_event to avoid
        # the production singleton.
        with patch("services.infrastructure.event_manager.get_event_manager",
                   return_value=MagicMock()):
            service._handle_donation_event(evt)
        assert service._cache == {}

    def test_handle_state_change_event_clears_cache(self, service):
        service._store_in_cache(MechStatusCacheResult(success=True), False)
        service._store_in_cache(MechStatusCacheResult(success=True), True)
        evt = SimpleNamespace(
            data={"old_power": 5.0, "new_power": 0.0},
            source_service="mech",
        )
        service._handle_state_change_event(evt)
        assert service._cache == {}

    def test_stop_background_loop_sets_flag(self, service):
        service._loop_running = True
        service.stop_background_loop()
        assert service._loop_running is False

    def test_stop_background_loop_cancels_task(self, service):
        fake_task = MagicMock()
        service._loop_task = fake_task
        service._loop_running = True
        service.stop_background_loop()
        fake_task.cancel.assert_called_once()
        assert service._loop_task is None

    def test_setup_event_listeners_registers_callbacks(self):
        # Don't suppress _setup_event_listeners here — exercise it.
        fake_event_manager = MagicMock()
        with patch("services.infrastructure.event_manager.get_event_manager",
                   return_value=fake_event_manager):
            svc = MechStatusCacheService()

        assert fake_event_manager.register_listener.call_count == 2
        registered_events = {
            call.args[0]
            for call in fake_event_manager.register_listener.call_args_list
        }
        assert registered_events == {
            "donation_completed", "mech_state_changed",
        }
        # Service is fully constructed.
        assert svc._cache == {}

    def test_setup_event_listeners_handles_import_error(self):
        # If event_manager import fails, the service must still construct.
        with patch("services.infrastructure.event_manager.get_event_manager",
                   side_effect=ImportError("missing")):
            svc = MechStatusCacheService()
        assert isinstance(svc, MechStatusCacheService)

    def test_handle_donation_event_emits_followup_event(self, service):
        evt = SimpleNamespace(
            data={"amount": 7.5},
            source_service="paypal",
        )
        fake_event_manager = MagicMock()
        with patch("services.infrastructure.event_manager.get_event_manager",
                   return_value=fake_event_manager):
            service._handle_donation_event(evt)

        fake_event_manager.emit_event.assert_called_once()
        kwargs = fake_event_manager.emit_event.call_args.kwargs
        assert kwargs["event_type"] == "discord_update_needed"
        assert kwargs["source_service"] == "mech_status_cache"

    def test_handle_donation_event_handles_bad_event(self, service):
        # Event without ``.data`` attribute → AttributeError → caught.
        bad_event = object()
        # No exception should escape.
        service._handle_donation_event(bad_event)

    def test_handle_state_change_event_handles_bad_event(self, service):
        bad_event = object()
        service._handle_state_change_event(bad_event)

    def test_background_refresh_invokes_decay_and_refreshes(self, service):
        import asyncio as _asyncio

        prog_state = _build_progress_state(power_current=10.0, is_offline=False)
        fake_progress = MagicMock()
        fake_progress.get_state.return_value = prog_state

        fresh = MechStatusCacheResult(success=True, level=2, power=10.0)
        with patch("services.mech.progress_service.get_progress_service",
                   return_value=fake_progress), \
             patch.object(service, "_fetch_fresh_status", return_value=fresh):
            _asyncio.run(service._background_refresh())

        fake_progress.get_state.assert_called_once()
        # Cache now contains both decimal variants.
        assert service._get_from_cache(False) is not None
        assert service._get_from_cache(True) is not None

    def test_background_refresh_logs_offline_state(self, service):
        import asyncio as _asyncio

        prog_state = _build_progress_state(power_current=0.0, is_offline=True)
        fake_progress = MagicMock()
        fake_progress.get_state.return_value = prog_state

        fresh = MechStatusCacheResult(success=True, level=1, power=0.0)
        with patch("services.mech.progress_service.get_progress_service",
                   return_value=fake_progress), \
             patch.object(service, "_fetch_fresh_status", return_value=fresh):
            _asyncio.run(service._background_refresh())

        assert service._get_from_cache(False) is not None

    def test_background_refresh_tolerates_decay_error(self, service):
        import asyncio as _asyncio

        fresh = MechStatusCacheResult(success=True)
        with patch("services.mech.progress_service.get_progress_service",
                   side_effect=ImportError("no progress")), \
             patch.object(service, "_fetch_fresh_status", return_value=fresh):
            # Should not raise.
            _asyncio.run(service._background_refresh())

        # Cache refresh proceeded despite decay failure.
        assert service._get_from_cache(False) is not None

    def test_start_background_loop_already_running_is_noop(self, service):
        import asyncio as _asyncio
        service._loop_running = True

        async def _runner():
            await service.start_background_loop()

        # Coroutine returns immediately because flag is set.
        _asyncio.run(_runner())
        # Flag is unchanged
        assert service._loop_running is True


# ===========================================================================
#                       mech_reset_service tests
# ===========================================================================
class TestMechResetService:
    """File operations, full-reset orchestration, audit info."""

    @pytest.fixture
    def reset_service(self, tmp_path):
        return MechResetService(config_dir=str(tmp_path))

    def test_init_with_absolute_path_uses_path_as_is(self, tmp_path):
        svc = MechResetService(config_dir=str(tmp_path))
        assert svc.config_dir == tmp_path
        assert svc.mech_state_file == tmp_path / "mech_state.json"

    def test_init_with_relative_path_resolves_against_project(self):
        svc = MechResetService(config_dir="custom_cfg")
        assert svc.config_dir.is_absolute()
        assert svc.config_dir.name == "custom_cfg"

    def test_cleanup_deprecated_files_removes_existing_file(self, reset_service):
        reset_service.achieved_levels_file.write_text(
            json.dumps({"levels": [1, 2, 3]}), encoding="utf-8")
        assert reset_service.achieved_levels_file.exists()

        out = reset_service.cleanup_deprecated_files()
        assert out.success is True
        assert "achieved_levels.json" in out.message
        assert not reset_service.achieved_levels_file.exists()

    def test_cleanup_deprecated_files_when_none_exist(self, reset_service):
        out = reset_service.cleanup_deprecated_files()
        assert out.success is True
        assert "No deprecated" in out.message

    def test_reset_mech_state_creates_when_missing(self, reset_service):
        # The function only writes when the file already exists / contains
        # data; with a missing file it writes a fresh dict with timestamp.
        out = reset_service.reset_mech_state()
        assert out.success is True
        # File now exists with at least a last_update entry.
        assert reset_service.mech_state_file.exists()
        data = json.loads(reset_service.mech_state_file.read_text())
        assert "last_update" in data

    def test_reset_mech_state_resets_glvl_per_channel(self, reset_service):
        reset_service.mech_state_file.write_text(json.dumps({
            "last_glvl_per_channel": {"123": 7, "456": 11},
            "mech_expanded_states": {"123": True, "456": True},
        }), encoding="utf-8")

        out = reset_service.reset_mech_state()
        assert out.success is True
        data = json.loads(reset_service.mech_state_file.read_text())
        assert all(v == 1 for v in data["last_glvl_per_channel"].values())
        assert all(v is False for v in data["mech_expanded_states"].values())
        assert "last_update" in data

    def test_reset_mech_state_handles_corrupt_json(self, reset_service):
        reset_service.mech_state_file.write_text("not-json", encoding="utf-8")
        out = reset_service.reset_mech_state()
        assert out.success is False
        assert "JSON" in out.message or "parsing" in out.message.lower()

    def test_reset_evolution_mode_no_file_is_ok(self, reset_service):
        out = reset_service.reset_evolution_mode()
        assert out.success is True
        assert "OK" in out.message

    def test_reset_evolution_mode_writes_defaults(self, reset_service):
        reset_service.evolution_mode_file.write_text(
            json.dumps({"use_dynamic": True, "difficulty_multiplier": 5.0}),
            encoding="utf-8")
        out = reset_service.reset_evolution_mode()
        assert out.success is True
        data = json.loads(reset_service.evolution_mode_file.read_text())
        assert data["use_dynamic"] is False
        assert data["difficulty_multiplier"] == 1.0
        assert "last_updated" in data

    def test_full_reset_success_path(self, reset_service):
        # Pre-populate optional files so each step has something to do.
        reset_service.evolution_mode_file.write_text(
            json.dumps({"use_dynamic": True}), encoding="utf-8")
        reset_service.achieved_levels_file.write_text(
            json.dumps({"levels": [1]}), encoding="utf-8")
        reset_service.mech_state_file.write_text(
            json.dumps({"last_glvl_per_channel": {"1": 5}}), encoding="utf-8")

        donation_ok = SimpleNamespace(success=True,
                                      message="Donations cleared",
                                      error_message=None)
        with patch("services.donation.unified_donation_service.reset_all_donations",
                   return_value=donation_ok):
            out = reset_service.full_reset()

        assert out.success is True
        assert "successful" in out.message.lower()
        assert out.details["operations"]
        # Cleanup actually removed the file.
        assert not reset_service.achieved_levels_file.exists()

    def test_full_reset_donation_failure_aborts(self, reset_service):
        donation_fail = SimpleNamespace(
            success=False, message="failed",
            error_message="db unavailable")
        with patch("services.donation.unified_donation_service.reset_all_donations",
                   return_value=donation_fail):
            out = reset_service.full_reset()
        assert out.success is False
        assert "Donation reset failed" in out.message

    def test_full_reset_handles_import_error(self, reset_service):
        with patch("services.donation.unified_donation_service.reset_all_donations",
                   side_effect=ImportError("no donation service")):
            out = reset_service.full_reset()
        assert out.success is False
        assert "Error" in out.message

    def test_full_reset_partial_warning_when_step_fails(self, reset_service):
        # mech_state_file with corrupt JSON triggers a state-reset failure
        # but donation reset still succeeds → overall success=False but
        # call still completes (no exception).
        reset_service.mech_state_file.write_text("not-json", encoding="utf-8")
        donation_ok = SimpleNamespace(success=True, message="ok",
                                      error_message=None)
        with patch("services.donation.unified_donation_service.reset_all_donations",
                   return_value=donation_ok):
            out = reset_service.full_reset()
        assert out.success is False
        assert "warnings" in out.message.lower()

    def test_get_current_status_aggregates_progress_state(self, reset_service):
        reset_service.mech_state_file.write_text(json.dumps({
            "last_glvl_per_channel": {"a": 1, "b": 2},
        }), encoding="utf-8")
        prog_state = _build_progress_state(level=4, evo_current=3.0,
                                           evo_max=10.0, total_donated=200.0)
        fake_progress = MagicMock()
        fake_progress.get_state.return_value = prog_state
        with patch("services.mech.progress_service.get_progress_service",
                   return_value=fake_progress), \
             patch("services.mech.mech_evolutions.get_evolution_level_info",
                   return_value=_build_evolution_info(name="Stomper")):
            status = reset_service.get_current_status()

        assert status["current_level"] == 4
        assert status["total_donated"] == 200.0
        assert status["next_level_name"] == "Stomper"
        assert status["channels_tracked"] == 2
        assert "architecture" in status

    def test_get_current_status_returns_max_level_at_11(self, reset_service):
        prog_state = _build_progress_state(level=11)
        fake_progress = MagicMock()
        fake_progress.get_state.return_value = prog_state
        with patch("services.mech.progress_service.get_progress_service",
                   return_value=fake_progress):
            status = reset_service.get_current_status()
        assert status["next_level_name"] == "OMEGA MECH (MAX)"
        assert status["next_level_threshold"] is None

    def test_get_current_status_handles_import_error(self, reset_service):
        with patch("services.mech.progress_service.get_progress_service",
                   side_effect=ImportError("no")):
            status = reset_service.get_current_status()
        assert "error" in status

    def test_quick_mech_reset_uses_singleton(self):
        donation_ok = SimpleNamespace(success=True, message="ok",
                                      error_message=None)
        with patch("services.donation.unified_donation_service.reset_all_donations",
                   return_value=donation_ok):
            res = quick_mech_reset()
        assert isinstance(res, ResetResult)

    def test_get_singleton_returns_same_instance(self):
        a = get_mech_reset_service()
        b = get_mech_reset_service()
        assert a is b


# ===========================================================================
#                       mech_state_manager tests
# ===========================================================================
class TestMechStateManager:
    """Discord state persistence — load / save / per-channel helpers."""

    @pytest.fixture
    def state_file(self, tmp_path):
        return tmp_path / "mech_state.json"

    @pytest.fixture
    def manager(self, state_file):
        return MechStateManager(state_file=str(state_file))

    def test_init_creates_state_file(self, state_file):
        # Pre-condition: file does not exist.
        assert not state_file.exists()
        MechStateManager(state_file=str(state_file))
        assert state_file.exists()
        assert json.loads(state_file.read_text()) == {}

    def test_save_and_load_state_roundtrip(self, manager):
        payload = {"hello": "world", "count": 5}
        manager.save_state(payload)
        # Force re-read
        loaded = manager.load_state()
        assert loaded == payload
        assert manager.state_cache == payload

    def test_load_state_handles_corrupt_file(self, manager, state_file):
        state_file.write_text("not-json")
        loaded = manager.load_state()
        assert loaded == {}

    def test_get_state_falls_back_to_default(self, manager):
        manager.save_state({"a": 1})
        assert manager.get_state("a") == 1
        assert manager.get_state("missing", default="xx") == "xx"

    def test_set_state_persists_to_disk(self, manager, state_file):
        manager.set_state("foo", 42)
        on_disk = json.loads(state_file.read_text())
        assert on_disk == {"foo": 42}

    def test_set_and_get_expanded_state(self, manager, state_file):
        manager.set_expanded_state("123", True)
        assert manager.get_expanded_state("123") is True
        # Defaults to False for unknown channels.
        assert manager.get_expanded_state("999") is False
        on_disk = json.loads(state_file.read_text())
        assert on_disk["mech_expanded_states"]["123"] is True

    def test_set_and_get_last_glvl(self, manager, state_file):
        manager.set_last_glvl("ch-1", 7)
        assert manager.get_last_glvl("ch-1") == 7
        # Default 0 for unknown channels.
        assert manager.get_last_glvl("ch-99") == 0
        on_disk = json.loads(state_file.read_text())
        assert on_disk["last_glvl_per_channel"]["ch-1"] == 7

    def test_force_recreate_rate_limits_within_window(self, manager):
        ch = "channel-1"
        # First call should allow recreate (no prior timestamp).
        assert manager.should_force_recreate(ch) is True
        manager.mark_force_recreate(ch)
        # Immediately after marking it must be blocked (within 30-second window).
        assert manager.should_force_recreate(ch) is False

    def test_force_recreate_persists_timestamp(self, manager, state_file):
        manager.mark_force_recreate("ch-x")
        on_disk = json.loads(state_file.read_text())
        assert "last_force_recreate" in on_disk
        assert "ch-x" in on_disk["last_force_recreate"]

    def test_save_state_handles_io_error(self, manager, state_file, caplog):
        # Replace the state_file with a path that is not writable: a directory.
        bad_path = state_file.parent / "subdir"
        bad_path.mkdir()
        manager.state_file = str(bad_path)  # writing to a dir raises IsADirectoryError → IOError
        manager.save_state({"a": 1})
        # No exception should escape.

    def test_get_singleton_returns_same_instance(self, monkeypatch, tmp_path):
        # Reset the module-level singleton, then redirect the default state
        # file into tmp_path so we don't touch the real config dir.
        import services.mech.mech_state_manager as msm
        msm._mech_state_manager = None
        # Patch the default __init__ argument by changing CWD.
        monkeypatch.chdir(tmp_path)
        a = get_mech_state_manager()
        b = get_mech_state_manager()
        assert a is b
        # Reset for cleanliness.
        msm._mech_state_manager = None
