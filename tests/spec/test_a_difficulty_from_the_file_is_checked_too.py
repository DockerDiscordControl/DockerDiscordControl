# -*- coding: utf-8 -*-
"""A difficulty multiplier read from the file is checked like one that is typed.

THE FINDING: setting the difficulty through the panel is bounds-checked
(0.1 to 10.0), but reading it back is not: get_evolution_mode_service hands
whatever stands in evolution_mode.json to the price calculation, which
multiplies with it. A 0 - a file edited by hand, a downgrade that wrote
something else, a truncated value - makes every level cost NOTHING: the
level-up loop then walks the mech from level 1 to 11 on a single cent,
because a goal of 0 is always reached, and the panel afterwards reports
"can level up" for ever.

The reader applies the same bounds as the writer and says when it had to.

COUNTER-CHECK (2026-09-22): red before - a multiplier of 0 came back as 0,
and the requirement for the next level was 0 cents.
"""

import json

import pytest

from services.config.config_service import ConfigService, GetEvolutionModeRequest


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    instance = ConfigService()
    instance.config_dir = tmp_path
    return instance


def _write(service, value):
    (service.config_dir / "evolution_mode.json").write_text(
        json.dumps({"use_dynamic": False, "difficulty_multiplier": value}), encoding="utf-8")


@pytest.mark.parametrize("value", [0, -1, 0.0001, 1000, "nonsense", None])
def test_a_multiplier_outside_the_range_falls_back(service, value):
    _write(service, value)

    result = service.get_evolution_mode_service(GetEvolutionModeRequest())

    assert ConfigService.MIN_DIFFICULTY_MULTIPLIER <= result.difficulty_multiplier \
        <= ConfigService.MAX_DIFFICULTY_MULTIPLIER, result.difficulty_multiplier


def test_a_multiplier_inside_the_range_is_used(service):
    """Counter-check: the operator's setting must survive the read."""
    _write(service, 2.5)

    assert service.get_evolution_mode_service(GetEvolutionModeRequest()).difficulty_multiplier == 2.5


def test_the_bounds_are_the_writer_s_bounds(service):
    """Counter-check: one rule, not two."""
    _write(service, ConfigService.MAX_DIFFICULTY_MULTIPLIER)

    result = service.get_evolution_mode_service(GetEvolutionModeRequest())

    assert result.difficulty_multiplier == ConfigService.MAX_DIFFICULTY_MULTIPLIER
