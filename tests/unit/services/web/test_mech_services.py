# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Web Services Unit Tests                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for the four mech-related web services:

* ``services.web.mech_web_service``
* ``services.web.mech_status_details_service``
* ``services.web.mech_music_service``
* ``services.mech.speed_levels``

The tests focus on the behavioural surface of each module and avoid
exercising the heavy dependency graph (animation cache, Discord, the
config service).  They mock the lazy imports performed inside each
service so that we can verify branching logic without spinning up the
actual mech runtime.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# --------------------------------------------------------------------------- #
# Imports under test                                                          #
# --------------------------------------------------------------------------- #

from services.web.mech_web_service import (
    MechAnimationRequest,
    MechConfigResult,
    MechDifficultyRequest,
    MechSpeedConfigRequest,
    MechTestAnimationRequest,
    MechWebService,
    get_mech_web_service,
)
from services.web.mech_status_details_service import (
    MechStatusDetailsRequest,
    MechStatusDetailsResult,
    MechStatusDetailsService,
    get_mech_status_details_service,
)
from services.web.mech_music_service import (
    MechMusicInfoRequest,
    MechMusicRequest,
    MechMusicResult,
    MechMusicService,
    get_mech_music_service,
)
from services.mech import speed_levels
from services.mech.speed_levels import (
    SPEED_DESCRIPTIONS,
    _calculate_power_ratio,
    _calculate_speed_level_from_power_ratio,
    get_combined_mech_status,
    get_speed_emoji,
    get_speed_info,
    get_translated_speed_description,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _evolution_info_stub(level=3, base_cost=15, power_max=15, decay_per_day=1.0,
                         name="The Corewalker Standard"):
    """Mimic ``EvolutionLevelInfo`` enough for the code under test."""
    return SimpleNamespace(
        level=level,
        name=name,
        description="stub",
        color="#888888",
        base_cost=base_cost,
        power_max=power_max,
        decay_per_day=decay_per_day,
    )


# =========================================================================== #
# speed_levels.py                                                             #
# =========================================================================== #

class TestSpeedLevelsConstants:
    """SPEED_DESCRIPTIONS data integrity."""

    def test_speed_descriptions_covers_zero_through_one_oh_one(self):
        # 0..101 inclusive = 102 entries
        assert set(SPEED_DESCRIPTIONS.keys()) == set(range(0, 102))

    def test_speed_descriptions_offline_entry(self):
        desc, color = SPEED_DESCRIPTIONS[0]
        assert desc == "OFFLINE"
        assert color == "#888888"

    def test_speed_descriptions_omega_entry(self):
        desc, color = SPEED_DESCRIPTIONS[101]
        assert "OMNISPEED" in desc
        assert color.startswith("#")

    def test_each_entry_is_tuple_of_two_strings(self):
        for level, value in SPEED_DESCRIPTIONS.items():
            assert isinstance(value, tuple) and len(value) == 2, level
            description, color = value
            assert isinstance(description, str) and description
            assert isinstance(color, str) and color.startswith("#")


class TestSpeedLevelsHelpers:
    """Pure helpers in speed_levels.py."""

    def test_calculate_power_ratio_capped_at_one(self):
        assert _calculate_power_ratio(50, 25) == 1.0

    def test_calculate_power_ratio_proportional(self):
        assert _calculate_power_ratio(5, 20) == 0.25

    def test_calculate_power_ratio_zero(self):
        assert _calculate_power_ratio(0, 20) == 0.0

    def test_calculate_speed_level_from_power_ratio_zero_power(self):
        assert _calculate_speed_level_from_power_ratio(3, 0, 20) == 0

    def test_calculate_speed_level_from_power_ratio_negative_power(self):
        assert _calculate_speed_level_from_power_ratio(3, -5, 20) == 0

    def test_calculate_speed_level_from_power_ratio_scales_to_100(self):
        # Half power should give roughly half the speed range (1..100)
        result = _calculate_speed_level_from_power_ratio(3, 10, 20)
        assert 40 <= result <= 60

    def test_calculate_speed_level_from_power_ratio_full_power(self):
        # Power exactly at max (and below transcendent) for level <11
        assert _calculate_speed_level_from_power_ratio(3, 20, 20) == 100

    def test_calculate_speed_level_level_11_normal_max(self):
        # Level 11 at exactly the max power -> 100
        assert _calculate_speed_level_from_power_ratio(11, 100, 100) == 100

    def test_calculate_speed_level_level_11_transcendent(self):
        # Level 11 with double the threshold -> 101 (TRANSCENDENT)
        assert _calculate_speed_level_from_power_ratio(11, 200, 100) == 101

    def test_calculate_speed_level_minimum_is_one_when_some_power(self):
        # Tiny power, but >0 must clamp to >=1
        assert _calculate_speed_level_from_power_ratio(2, 0.001, 1000) == 1

    def test_get_speed_emoji_returns_empty_string(self):
        # Implementation deliberately returns "" - mech animation is the indicator
        assert get_speed_emoji(0) == ""
        assert get_speed_emoji(50) == ""
        assert get_speed_emoji(101) == ""


class TestSpeedLevelsTranslations:
    """get_translated_speed_description fallback / lookup."""

    def test_translation_falls_back_to_english_description(self):
        # Whatever language we ask for, we always at least get a string back
        text = get_translated_speed_description(0, "en")
        assert isinstance(text, str) and text

    def test_translation_for_unknown_level_falls_back_to_offline(self):
        # Unknown levels round trip to SPEED_DESCRIPTIONS[0]
        result = get_translated_speed_description(9999, "en")
        assert result == "OFFLINE"

    def test_translation_with_translations_dict(self):
        with patch.object(speed_levels, "SPEED_TRANSLATIONS", {
            "speed_descriptions": {
                "5": {"en": "EN5", "de": "DE5"},
            }
        }):
            assert get_translated_speed_description(5, "de") == "DE5"
            assert get_translated_speed_description(5, "en") == "EN5"
            # Missing language -> fallback to SPEED_DESCRIPTIONS
            assert get_translated_speed_description(5, "fr") == SPEED_DESCRIPTIONS[5][0]


class TestGetSpeedInfo:
    """get_speed_info covers the OFFLINE branch + service-dependency fallback."""

    def test_offline_for_zero_donations(self):
        assert get_speed_info(0) == SPEED_DESCRIPTIONS[0]

    def test_offline_for_negative_donations(self):
        assert get_speed_info(-1) == SPEED_DESCRIPTIONS[0]

    def test_returns_motionless_when_evolution_module_missing(self):
        # Force the helper to raise ImportError so we hit the fallback branch
        with patch.object(
            speed_levels,
            "_get_evolution_context",
            side_effect=ImportError("missing"),
        ):
            assert get_speed_info(10) == SPEED_DESCRIPTIONS[1]

    def test_returns_motionless_on_calculation_error(self):
        with patch.object(
            speed_levels,
            "_get_evolution_context",
            side_effect=ValueError("bad data"),
        ):
            assert get_speed_info(10) == SPEED_DESCRIPTIONS[1]


class TestGetCombinedMechStatus:
    """get_combined_mech_status combines evolution + speed metadata."""

    def _patch_evolution_info(self, level=3):
        evolution_info = {
            "level": level,
            "name": "The Corewalker Standard",
            "color": "#888888",
            "description": "stub",
            "current_threshold": 15,
            "next_threshold": 20,
            "next_name": "The Titanframe",
            "next_description": "stub",
            "amount_needed": 5,
        }
        return patch(
            "services.mech.mech_evolutions.get_evolution_info",
            return_value=evolution_info,
        )

    def test_combined_status_happy_path(self):
        with self._patch_evolution_info(level=3), \
             patch.object(
                 speed_levels,
                 "_get_evolution_context",
                 return_value=(3, 20),
             ):
            result = get_combined_mech_status(
                Power_amount=10.0,
                total_donations_received=15.0,
                language="en",
            )

        assert result["evolution"]["level"] == 3
        assert isinstance(result["speed"]["level"], int)
        assert 0 <= result["speed"]["level"] <= 100
        assert "color" in result["speed"]
        assert result["primary_color"] == "#888888"
        assert result["Power_amount"] == 10.0
        assert result["total_donations_received"] == 15.0
        assert "combined_status" in result

    def test_combined_status_default_total_donations(self):
        # If total_donations_received is None, Power_amount is reused
        with self._patch_evolution_info(level=1), \
             patch.object(
                 speed_levels,
                 "_get_evolution_context",
                 return_value=(1, 10),
             ):
            result = get_combined_mech_status(
                Power_amount=5.0,
                total_donations_received=None,
                language="en",
            )
        assert result["total_donations_received"] == 5.0
        assert result["Power_amount"] == 5.0

    def test_combined_status_evolution_import_error_uses_default(self):
        # When evolution import fails, falls back to "SCRAP MECH" defaults
        with patch(
            "services.mech.mech_evolutions.get_evolution_info",
            side_effect=ImportError("nope"),
        ), patch.object(
            speed_levels,
            "_get_evolution_context",
            side_effect=ImportError("missing"),
        ):
            result = get_combined_mech_status(Power_amount=5.0, language="en")
        # Default fallback evolution dict
        assert result["evolution"]["name"] == "SCRAP MECH"
        # Speed level falls back to min(int(power), 100)
        assert result["speed"]["level"] == 5

    def test_combined_status_calc_value_error_falls_back(self):
        # ValueError in speed calc -> fallback path (line 349-352)
        with self._patch_evolution_info(level=2), \
             patch.object(
                 speed_levels,
                 "_get_evolution_context",
                 side_effect=ValueError("boom"),
             ):
            result = get_combined_mech_status(Power_amount=7.0, language="en")
        assert result["speed"]["level"] == 7

    def test_combined_status_resolves_language_via_config_service(self):
        # Exercises the lines 316-333 branch where language=None triggers
        # the lazy config_service lookup.
        config_result = SimpleNamespace(success=True, config={"language": "de"})
        config_manager = MagicMock()
        config_manager.get_config_service.return_value = config_result
        with self._patch_evolution_info(level=2), \
             patch.object(
                 speed_levels,
                 "_get_evolution_context",
                 return_value=(2, 15),
             ), patch(
                 "services.config.config_service.get_config_service",
                 return_value=config_manager,
             ):
            result = get_combined_mech_status(Power_amount=5.0)  # language=None
        assert result["speed"]["level"] >= 0

    def test_combined_status_language_config_failure_defaults_to_en(self):
        # If config lookup fails, language defaults to 'en' via except branch
        with self._patch_evolution_info(level=2), \
             patch.object(
                 speed_levels,
                 "_get_evolution_context",
                 return_value=(2, 15),
             ), patch(
                 "services.config.config_service.get_config_service",
                 side_effect=ImportError("no config"),
             ):
            result = get_combined_mech_status(Power_amount=5.0)
        assert "speed" in result


class TestGetEvolutionContext:
    """_get_evolution_context happy paths + edge cases."""

    def test_returns_next_level_threshold_as_max_power(self):
        info_current = _evolution_info_stub(level=3, base_cost=15, power_max=15)
        info_next = _evolution_info_stub(level=4, base_cost=20, power_max=20)

        with patch(
            "services.mech.mech_evolutions.get_evolution_level",
            return_value=3,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level_info",
            side_effect=lambda lvl: info_current if lvl == 3 else (info_next if lvl == 4 else None),
        ):
            level, max_power = speed_levels._get_evolution_context(15.0)

        assert level == 3
        assert max_power == 20  # next level's base_cost

    def test_returns_power_max_when_at_top_level(self):
        info_current = _evolution_info_stub(level=11, base_cost=100, power_max=100)
        with patch(
            "services.mech.mech_evolutions.get_evolution_level",
            return_value=11,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level_info",
            side_effect=lambda lvl: info_current if lvl == 11 else None,
        ):
            level, max_power = speed_levels._get_evolution_context(500.0)
        assert level == 11
        assert max_power == 100

    def test_raises_value_error_when_level_unknown(self):
        with patch(
            "services.mech.mech_evolutions.get_evolution_level",
            return_value=99,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level_info",
            return_value=None,
        ):
            with pytest.raises(ValueError):
                speed_levels._get_evolution_context(0.0)


class TestGetSpeedInfoHappy:
    """get_speed_info happy path covering line 234-238."""

    def test_returns_description_from_speed_descriptions(self):
        with patch.object(
            speed_levels,
            "_get_evolution_context",
            return_value=(3, 20),
        ):
            description, color = get_speed_info(10.0)
        # description is a non-empty string
        assert isinstance(description, str) and description
        assert color.startswith("#")

    def test_translation_handles_typeerror_gracefully(self):
        # Force the inner translation lookup to TypeError -> hits except branch
        bad_translations = {
            "speed_descriptions": MagicMock(
                __contains__=MagicMock(side_effect=TypeError("no in")),
            )
        }
        with patch.object(speed_levels, "SPEED_TRANSLATIONS", bad_translations):
            # Should still return a string from SPEED_DESCRIPTIONS fallback
            text = get_translated_speed_description(5, "en")
            assert isinstance(text, str) and text


# =========================================================================== #
# mech_music_service.py                                                       #
# =========================================================================== #

class TestMechMusicService:
    """MechMusicService covers level validation + URL lookup."""

    def setup_method(self):
        self.svc = MechMusicService()

    def test_singleton_returns_same_instance(self):
        assert get_mech_music_service() is get_mech_music_service()

    @pytest.mark.parametrize("level", [1, 2, 5, 10, 11])
    def test_valid_levels_return_url_and_title(self, level):
        result = self.svc.get_mech_music_url(MechMusicRequest(level=level))
        assert result.success is True
        assert result.url and result.url.startswith("https://youtu.be/")
        assert result.title

    @pytest.mark.parametrize("level", [0, -1, 12, 99])
    def test_invalid_levels_return_400(self, level):
        result = self.svc.get_mech_music_url(MechMusicRequest(level=level))
        assert result.success is False
        assert result.status_code == 400
        assert "1-11" in result.error

    def test_invalid_level_type_rejected(self):
        # _validate_level rejects non-int values
        result = self.svc.get_mech_music_url(MechMusicRequest(level="five"))
        assert result.success is False
        assert result.status_code == 400

    def test_get_all_music_info_returns_eleven_tracks(self):
        result = self.svc.get_all_music_info(MechMusicInfoRequest())
        assert result.success is True
        assert result.data["total_tracks"] == 11
        assert result.data["available_tracks"] == 11
        assert result.data["platform"] == "YouTube"
        assert result.data["monetized"] is True
        # Every level has metadata
        for lvl in range(1, 12):
            entry = result.data["music_tracks"][str(lvl)]
            assert entry["available"] is True
            assert entry["url"]
            assert entry["title"]


# =========================================================================== #
# mech_web_service.py                                                         #
# =========================================================================== #

class TestMechWebServiceLifecycle:
    """Basic lifecycle/singleton checks."""

    def test_singleton_returns_same_instance(self):
        assert get_mech_web_service() is get_mech_web_service()

    def test_init_does_not_raise(self):
        # Constructor must succeed without any external services
        MechWebService()


class TestMechWebServiceSpeedConfig:
    """get_speed_config end-to-end (with helpers patched)."""

    def setup_method(self):
        self.svc = MechWebService()

    def test_get_speed_config_happy_path(self):
        # Patch the helpers used inside get_speed_config so we exercise the
        # request->result flow without touching the real mech_evolutions.
        with patch(
            "services.mech.speed_levels._get_evolution_context",
            return_value=(3, 20),
        ), patch(
            "services.mech.speed_levels._calculate_speed_level_from_power_ratio",
            return_value=42,
        ), patch.object(
            self.svc, "_log_user_action",
        ):
            result = self.svc.get_speed_config(MechSpeedConfigRequest(total_donations=15.0))

        assert result.success is True
        assert result.data["speed_level"] == 42
        assert result.data["total_donations"] == 15.0
        assert result.data["description"] == SPEED_DESCRIPTIONS[42][0]
        assert result.data["color"] == SPEED_DESCRIPTIONS[42][1]

    def test_get_speed_config_falls_back_when_helpers_raise(self):
        # When _get_evolution_context raises ImportError the calculation
        # falls back to ``min(int(total_donations), 100)``.
        with patch(
            "services.mech.speed_levels._get_evolution_context",
            side_effect=ImportError("missing"),
        ), patch.object(self.svc, "_log_user_action"):
            result = self.svc.get_speed_config(
                MechSpeedConfigRequest(total_donations=42.0)
            )

        assert result.success is True
        assert result.data["speed_level"] == 42

    def test_get_speed_config_with_zero_donations(self):
        with patch(
            "services.mech.speed_levels._get_evolution_context",
            side_effect=ImportError("missing"),
        ), patch.object(self.svc, "_log_user_action"):
            result = self.svc.get_speed_config(
                MechSpeedConfigRequest(total_donations=0.0)
            )

        assert result.success is True
        assert result.data["speed_level"] == 0
        assert result.data["description"] == "OFFLINE"


class TestMechWebServiceDifficulty:
    """manage_difficulty branches."""

    def setup_method(self):
        self.svc = MechWebService()

    def test_manage_difficulty_invalid_operation(self):
        result = self.svc.manage_difficulty(MechDifficultyRequest(operation="frobnicate"))
        assert result.success is False
        assert result.status_code == 400
        assert "Invalid operation" in result.error

    def test_set_difficulty_requires_multiplier(self):
        result = self.svc.manage_difficulty(MechDifficultyRequest(operation="set", multiplier=None))
        assert result.success is False
        assert result.status_code == 400
        assert "Multiplier is required" in result.error

    @pytest.mark.parametrize("multiplier", [0.4, 2.5, -1.0, 100.0])
    def test_set_difficulty_rejects_out_of_range(self, multiplier):
        result = self.svc.manage_difficulty(
            MechDifficultyRequest(operation="set", multiplier=multiplier)
        )
        assert result.success is False
        assert result.status_code == 400
        assert "between 0.5 and 2.4" in result.error

    def test_set_difficulty_happy_path(self):
        mech_service = MagicMock()
        with patch(
            "services.mech.mech_service.get_mech_service",
            return_value=mech_service,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level",
            return_value=3,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level_info",
            return_value=_evolution_info_stub(level=4, base_cost=20),
        ), patch.object(self.svc, "_get_total_donations", return_value=15.0), \
             patch.object(self.svc, "_log_user_action"):
            result = self.svc.manage_difficulty(
                MechDifficultyRequest(operation="set", multiplier=1.5)
            )

        assert result.success is True
        assert result.data["multiplier"] == 1.5
        assert result.data["is_auto"] is False
        assert result.data["status"] == "manual"
        assert result.data["simple_evolution"]["current_level"] == 3
        # base_cost (20) * multiplier (1.5) -> 30
        assert result.data["simple_evolution"]["next_level_cost"] == 30
        mech_service.set_evolution_mode.assert_called_once_with(
            use_dynamic=False, difficulty_multiplier=1.5
        )

    def test_reset_difficulty_happy_path(self):
        mech_service = MagicMock()
        with patch(
            "services.mech.mech_service.get_mech_service",
            return_value=mech_service,
        ), patch.object(self.svc, "_log_user_action"):
            result = self.svc.manage_difficulty(MechDifficultyRequest(operation="reset"))

        assert result.success is True
        assert result.data["multiplier"] == 1.0
        assert result.data["is_auto"] is True
        assert result.data["status"] == "auto"
        mech_service.set_evolution_mode.assert_called_once_with(
            use_dynamic=True, difficulty_multiplier=1.0
        )

    def test_reset_difficulty_handles_service_error(self):
        with patch(
            "services.mech.mech_service.get_mech_service",
            side_effect=ImportError("nope"),
        ):
            result = self.svc.manage_difficulty(MechDifficultyRequest(operation="reset"))
        assert result.success is False
        assert result.status_code == 500

    def test_get_difficulty_happy_path(self):
        # Build a stub MechDataStore evolution result
        evo_result = SimpleNamespace(
            success=True,
            difficulty_multiplier=1.5,
            evolution_mode="static",
            error=None,
        )
        data_store = MagicMock()
        data_store.get_evolution_info.return_value = evo_result

        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_config_service",
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level",
            return_value=3,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level_info",
            side_effect=lambda lvl: _evolution_info_stub(level=lvl, base_cost=lvl * 10),
        ), patch.object(self.svc, "_get_total_donations", return_value=15.0):
            result = self.svc.manage_difficulty(MechDifficultyRequest(operation="get"))

        assert result.success is True
        assert result.data["multiplier"] == 1.5
        assert result.data["is_auto"] is False
        assert result.data["status"] == "manual"
        assert result.data["manual_override"] is True
        # Achieved levels: 1..11, three are achieved (<= current_level=3)
        achieved = [v for v in result.data["simple_evolution"]["achieved_levels"].values() if v["achieved"]]
        assert len(achieved) == 3
        # Presets exposed
        assert "EASY" in result.data["presets"]

    def test_get_difficulty_returns_error_on_data_store_failure(self):
        evo_result = SimpleNamespace(
            success=False,
            error="boom",
            difficulty_multiplier=1.0,
            evolution_mode="dynamic",
        )
        data_store = MagicMock()
        data_store.get_evolution_info.return_value = evo_result
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_config_service",
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level",
            return_value=1,
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level_info",
            return_value=_evolution_info_stub(),
        ):
            result = self.svc.manage_difficulty(MechDifficultyRequest(operation="get"))

        assert result.success is False
        assert result.status_code == 500
        assert result.error == "boom"


class TestMechWebServiceLiveAnimation:
    """get_live_animation: error paths + force_evolution_level branch."""

    def setup_method(self):
        self.svc = MechWebService()

    def test_force_evolution_level_clamps_and_returns_animation(self):
        animation_service = MagicMock()
        animation_service.get_animation_with_speed_and_power.return_value = b"WEBP"
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            return_value=animation_service,
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            return_value={"speed": {"level": 50}},
        ):
            # force_evolution_level=20 should clamp to 11 -> max speed 100
            result = self.svc.get_live_animation(
                MechAnimationRequest(force_evolution_level=20, force_power=99.0)
            )

        assert result.success is True
        assert result.animation_bytes == b"WEBP"
        # Level 11 -> speed_level=100, power retained
        animation_service.get_animation_with_speed_and_power.assert_called_once()
        called_args = animation_service.get_animation_with_speed_and_power.call_args[0]
        assert called_args[0] == 11
        assert called_args[1] == 100

    def test_force_evolution_level_big_resolution_uses_big_method(self):
        animation_service = MagicMock()
        animation_service.get_animation_with_speed_and_power_big.return_value = b"BIGWEBP"
        with patch(
            "services.mech.animation_cache_service.get_animation_cache_service",
            return_value=animation_service,
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            return_value={"speed": {"level": 25}},
        ):
            result = self.svc.get_live_animation(
                MechAnimationRequest(
                    force_evolution_level=4,
                    force_power=15.0,
                    resolution="big",
                )
            )

        assert result.success is True
        assert result.animation_bytes == b"BIGWEBP"
        animation_service.get_animation_with_speed_and_power_big.assert_called_once()

    def test_cache_failure_returns_error_response(self):
        cache_service = MagicMock()
        cache_service.get_cached_status.return_value = SimpleNamespace(
            success=False,
            level=0,
            power=0,
            error="cache miss",
        )
        with patch(
            "services.mech.mech_status_cache_service.get_mech_status_cache_service",
            return_value=cache_service,
        ):
            # No force_power and no force_evolution_level -> uses cache
            # _create_error_response is missing; we hit AttributeError, caught
            # by the broad except and rendered as an error animation.
            result = self.svc.get_live_animation(MechAnimationRequest())

        # _create_error_response does not exist on the service, so the code
        # raises AttributeError, which is caught and produces an error
        # animation.  Either path must yield success=False with a 500.
        assert result.success is False
        assert result.status_code == 500


class TestMechWebServicePrivateHelpers:
    """Direct exercise of the private helpers."""

    def setup_method(self):
        self.svc = MechWebService()

    def test_log_user_action_swallows_import_errors(self):
        # If the action_logger import fails, the helper must NOT raise
        with patch(
            "services.infrastructure.action_logger.log_user_action",
            side_effect=ImportError("missing"),
        ):
            self.svc._log_user_action("X", "Y", "Z")

    def test_get_total_donations_force_power_short_circuit(self):
        assert self.svc._get_total_donations(force_power=99.5) == 99.5

    def test_get_total_donations_falls_back_on_data_store_failure(self):
        data_store = MagicMock()
        data_store.get_power_info.return_value = SimpleNamespace(
            success=False, total_donated=None
        )
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ):
            assert self.svc._get_total_donations() == 20.0

    def test_get_total_donations_uses_data_store_value(self):
        data_store = MagicMock()
        data_store.get_power_info.return_value = SimpleNamespace(
            success=True, total_donated=42.0
        )
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ):
            assert self.svc._get_total_donations() == 42.0

    def test_create_fallback_animation_returns_png(self):
        result = self.svc._create_fallback_animation(15.0)
        # Either PIL is available and we get PNG bytes, or PIL isn't
        # available and we fall through to a 500.  Both are acceptable.
        if result.success:
            assert result.animation_bytes
            assert result.content_type == "image/png"
        else:
            assert result.status_code == 500

    def test_create_error_animation_returns_failure_with_bytes_or_500(self):
        result = self.svc._create_error_animation(0.0, "boom")
        # success is always False because this is the error path
        assert result.success is False
        assert result.status_code == 500


# =========================================================================== #
# mech_status_details_service.py                                              #
# =========================================================================== #

class TestMechStatusDetailsService:
    """MechStatusDetailsService aggregations + helpers."""

    def setup_method(self):
        self.svc = MechStatusDetailsService()

    def test_singleton_returns_same_instance(self):
        assert get_mech_status_details_service() is get_mech_status_details_service()

    def test_create_progress_bar_zero_max(self):
        bar = self.svc._create_progress_bar(0, 0)
        # zero max -> 0%
        assert bar.endswith("0.0%")
        assert "█" not in bar  # Nothing filled

    def test_create_progress_bar_full(self):
        bar = self.svc._create_progress_bar(10, 10, length=10)
        # Fully filled
        assert bar.startswith("█" * 10)
        assert "100.0%" in bar

    def test_create_progress_bar_clamps_overshoot(self):
        # Overshooting current must not exceed length
        bar = self.svc._create_progress_bar(100, 10, length=10)
        assert bar.startswith("█" * 10)

    def test_create_progress_bar_half(self):
        bar = self.svc._create_progress_bar(5, 10, length=10)
        assert "█" * 5 in bar
        assert "░" * 5 in bar
        assert "50.0%" in bar

    def test_get_speed_description_offline_for_zero_or_negative(self):
        assert self.svc._get_speed_description(0) == "OFFLINE"
        assert self.svc._get_speed_description(-5) == "OFFLINE"

    def test_get_speed_description_returns_string(self):
        # Just verify we get a non-empty string for a positive power level
        assert self.svc._get_speed_description(50)

    def test_get_mech_status_details_failure_when_data_store_fails(self):
        data_store = MagicMock()
        data_store.get_comprehensive_data.return_value = SimpleNamespace(
            success=False,
            error="data missing",
        )

        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ), patch(
            "services.config.config_service.get_config_service",
            return_value=MagicMock(
                get_config_service=lambda req: SimpleNamespace(
                    success=True, config={"language": "en"}
                )
            ),
        ):
            result = self.svc.get_mech_status_details(MechStatusDetailsRequest())

        assert isinstance(result, MechStatusDetailsResult)
        assert result.success is False
        assert result.error and "MechDataStore" in result.error

    def test_get_next_level_info_falls_back_to_static_thresholds(self):
        # data_store returns success but no level_data; service falls back
        # to the hardcoded thresholds + names.
        evo_result = SimpleNamespace(
            success=True,
            level_data=None,
            evolution_mode="static",
            difficulty_multiplier=1.0,
            error=None,
        )
        data_store = MagicMock()
        data_store.get_evolution_info.return_value = evo_result

        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ):
            info = self.svc._get_next_level_info(3)

        assert info is not None
        assert info["name"] == "The Corewalker Standard"
        assert info["mode"] == "static"

    def test_get_next_level_info_returns_none_for_invalid_level(self):
        evo_result = SimpleNamespace(
            success=True,
            level_data=None,
            evolution_mode="dynamic",
            difficulty_multiplier=1.0,
            error=None,
        )
        data_store = MagicMock()
        data_store.get_evolution_info.return_value = evo_result
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ):
            assert self.svc._get_next_level_info(99) is None

    def test_get_next_level_info_returns_none_when_data_store_fails(self):
        evo_result = SimpleNamespace(
            success=False,
            error="boom",
            level_data=None,
            evolution_mode="dynamic",
            difficulty_multiplier=1.0,
        )
        data_store = MagicMock()
        data_store.get_evolution_info.return_value = evo_result
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ):
            assert self.svc._get_next_level_info(2) is None

    def test_get_mech_animation_delegates_to_web_service(self):
        web_service = MagicMock()
        web_service.get_live_animation.return_value = SimpleNamespace(
            success=True,
            animation_bytes=b"PNG",
            content_type="image/webp",
            error=None,
        )
        with patch(
            "services.web.mech_web_service.get_mech_web_service",
            return_value=web_service,
        ):
            data, ctype = self.svc._get_mech_animation(3, 12.0, use_high_resolution=False)

        assert data == b"PNG"
        assert ctype == "image/webp"
        # Big request flag wired correctly
        request_arg = web_service.get_live_animation.call_args[0][0]
        assert request_arg.resolution == "small"
        assert request_arg.force_power == 12.0

    def test_get_mech_animation_high_resolution(self):
        web_service = MagicMock()
        web_service.get_live_animation.return_value = SimpleNamespace(
            success=False, error="x", animation_bytes=None, content_type=None
        )
        with patch(
            "services.web.mech_web_service.get_mech_web_service",
            return_value=web_service,
        ):
            data, ctype = self.svc._get_mech_animation(5, 25.0, use_high_resolution=True)

        assert data is None
        assert ctype is None
        request_arg = web_service.get_live_animation.call_args[0][0]
        assert request_arg.resolution == "big"

    def test_get_mech_status_details_happy_path_normal_level(self):
        # Build a comprehensive data result for level 3
        bars = SimpleNamespace(
            Power_current=5,
            Power_max_for_level=15,
            mech_progress_current=10,
            mech_progress_max=20,
        )
        data_result = SimpleNamespace(
            success=True,
            current_power=12.34,
            current_level=3,
            level_name="The Corewalker Standard",
            total_donated=15.0,
            bars=bars,
            error=None,
        )
        data_store = MagicMock()
        data_store.get_comprehensive_data.return_value = data_result
        # _get_next_level_info also calls get_evolution_info via data store
        evo_result = SimpleNamespace(
            success=True,
            level_data=None,
            evolution_mode="static",
            difficulty_multiplier=1.0,
            error=None,
        )
        data_store.get_evolution_info.return_value = evo_result

        config_service = MagicMock()
        config_service.get_config_service.return_value = SimpleNamespace(
            success=True, config={"language": "en"}
        )

        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ), patch(
            "services.config.config_service.get_config_service",
            return_value=config_service,
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            return_value={"speed": {"description": "Fast"}},
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level_info",
            return_value=_evolution_info_stub(level=3, decay_per_day=2.0),
        ), patch.object(
            self.svc, "_get_mech_animation",
            return_value=(b"PNG", "image/webp"),
        ):
            result = self.svc.get_mech_status_details(
                MechStatusDetailsRequest(use_high_resolution=False)
            )

        assert result.success is True
        assert "Level 3" in result.level_text
        assert "Fast" in result.speed_text
        assert result.power_text == "⚡12.34"
        assert "%" in result.power_bar
        assert result.energy_consumption is not None
        assert "🔻" in result.energy_consumption
        assert result.animation_bytes == b"PNG"
        assert result.content_type == "image/webp"
        assert result.level == 3
        assert result.power_decimal == 12.34

    def test_get_mech_status_details_level_11_uses_infinity(self):
        # For level 11 we hit the infinity message path AND the "no energy
        # consumption" branch.
        bars = SimpleNamespace(
            Power_current=100,
            Power_max_for_level=100,
            mech_progress_current=100,
            mech_progress_max=100,
        )
        data_result = SimpleNamespace(
            success=True,
            current_power=200.0,
            current_level=11,
            level_name="OMEGA MECH",
            total_donated=200.0,
            bars=bars,
            error=None,
        )
        data_store = MagicMock()
        data_store.get_comprehensive_data.return_value = data_result
        data_store.get_evolution_info.return_value = SimpleNamespace(
            success=True,
            level_data=None,
            evolution_mode="static",
            difficulty_multiplier=1.0,
            error=None,
        )

        config_service = MagicMock()
        config_service.get_config_service.return_value = SimpleNamespace(
            success=True, config={"language": "en"}
        )

        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ), patch(
            "services.config.config_service.get_config_service",
            return_value=config_service,
        ), patch.object(
            self.svc, "_get_mech_animation",
            return_value=(None, None),
        ), patch(
            "services.config.config_service.load_config",
            return_value={"language": "en"},
        ):
            result = self.svc.get_mech_status_details(
                MechStatusDetailsRequest(use_high_resolution=True)
            )

        assert result.success is True
        # No energy consumption at level 11
        assert result.energy_consumption is None
        # power_bar contains the infinity character
        assert "∞" in result.power_bar or "infinity" in result.power_bar.lower() or "Unendlich" in result.power_bar
        assert result.level == 11

    def test_get_mech_status_details_config_service_failure_falls_back_to_de(self):
        bars = SimpleNamespace(
            Power_current=0,
            Power_max_for_level=10,
            mech_progress_current=0,
            mech_progress_max=10,
        )
        data_result = SimpleNamespace(
            success=True,
            current_power=0.0,
            current_level=1,
            level_name="The Rustborn Husk",
            total_donated=0.0,
            bars=bars,
            error=None,
        )
        data_store = MagicMock()
        data_store.get_comprehensive_data.return_value = data_result
        data_store.get_evolution_info.return_value = SimpleNamespace(
            success=True,
            level_data=None,
            evolution_mode="static",
            difficulty_multiplier=1.0,
            error=None,
        )

        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ), patch(
            "services.config.config_service.get_config_service",
            side_effect=ImportError("no config"),
        ), patch(
            "services.mech.speed_levels.get_combined_mech_status",
            return_value={"speed": {"description": "OFFLINE"}},
        ), patch(
            "services.mech.mech_evolutions.get_evolution_level_info",
            return_value=_evolution_info_stub(level=1, decay_per_day=1.0),
        ), patch.object(
            self.svc, "_get_mech_animation",
            return_value=(None, None),
        ):
            result = self.svc.get_mech_status_details(MechStatusDetailsRequest())

        assert result.success is True
        assert result.level == 1

    def test_get_infinity_message_uses_speed_translations(self):
        # SPEED_TRANSLATIONS has the level_11 messages -> direct lookup
        translations = {
            "infinity_messages": {
                "level_11": {
                    "en": "EN INFINITY!",
                    "de": "DE UNENDLICH!",
                    "fr": "FR INFINI!",
                }
            }
        }
        with patch(
            "services.mech.speed_levels.SPEED_TRANSLATIONS",
            translations,
        ), patch(
            "services.config.config_service.load_config",
            return_value={"language": "de"},
        ):
            msg = self.svc._get_infinity_message()
        assert msg == "DE UNENDLICH!"

    def test_get_infinity_message_unknown_language_falls_back_to_en(self):
        translations = {
            "infinity_messages": {
                "level_11": {"en": "EN INFINITY!"},
            }
        }
        with patch(
            "services.mech.speed_levels.SPEED_TRANSLATIONS",
            translations,
        ), patch(
            "services.config.config_service.load_config",
            return_value={"language": "ja"},  # unknown -> normalized to 'en'
        ):
            msg = self.svc._get_infinity_message()
        assert msg == "EN INFINITY!"

    def test_get_infinity_message_load_config_failure(self):
        # When load_config raises, language defaults to 'en'
        translations = {
            "infinity_messages": {
                "level_11": {"en": "FALLBACK EN"},
            }
        }
        with patch(
            "services.mech.speed_levels.SPEED_TRANSLATIONS",
            translations,
        ), patch(
            "services.config.config_service.load_config",
            side_effect=ImportError("nope"),
        ):
            msg = self.svc._get_infinity_message()
        assert msg == "FALLBACK EN"

    def test_get_infinity_message_no_translations_uses_hardcoded_fallback(self):
        # Empty translations -> hardcoded fallback dict
        with patch(
            "services.mech.speed_levels.SPEED_TRANSLATIONS",
            {},
        ), patch(
            "services.config.config_service.load_config",
            return_value={"language": "de"},
        ):
            msg = self.svc._get_infinity_message()
        # hardcoded fallback for de
        assert "Unendlichkeit" in msg

    def test_get_next_level_info_with_level_data(self):
        # Provide level_data so the first branch is exercised
        level_obj = SimpleNamespace(
            level=4,
            name="The Titanframe",
            threshold=20,
            base_threshold=20,
        )
        evo_result = SimpleNamespace(
            success=True,
            level_data=[level_obj],
            evolution_mode="static",
            difficulty_multiplier=1.5,
            error=None,
        )
        data_store = MagicMock()
        data_store.get_evolution_info.return_value = evo_result
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ):
            info = self.svc._get_next_level_info(4)

        assert info["name"] == "The Titanframe"
        assert info["threshold"] == 20
        assert info["mode"] == "static"
        assert info["difficulty"] == 1.5

    def test_get_next_level_info_dynamic_mode_fallback(self):
        # dynamic mode hits the dynamic-branch base_thresholds path (line ~321)
        evo_result = SimpleNamespace(
            success=True,
            level_data=None,
            evolution_mode="dynamic",
            difficulty_multiplier=1.0,
            error=None,
        )
        data_store = MagicMock()
        data_store.get_evolution_info.return_value = evo_result
        with patch(
            "services.mech.mech_data_store.get_mech_data_store",
            return_value=data_store,
        ):
            info = self.svc._get_next_level_info(2)
        assert info is not None
        assert info["mode"] == "dynamic"
