# -*- coding: utf-8 -*-
"""The difficulty clamp keeps the cost range it says it keeps.

THE FINDING (review C69, section 22 F3): ``set_difficulty_multiplier``
clamps to 0.25-2.5 with the comment

    # Clamp multiplier to ensure Level 2 stays between $5-$50
    # Base cost for Level 2 is $20, so multiplier range is 0.25-2.5

The base cost for level 2 is not $20. ``_get_fallback_config`` - which is
what every installation without its own ``evolution.json`` actually uses -
gives level 2 a cost of $10. With that, the clamp's reachable range is
$2.50-$25: half of what the comment promises at the top, and below the floor
it promises at the bottom.

The bounds are derived from the base cost now, so the sentence in the comment
is a statement about the code rather than about a number that used to be
somewhere. Nothing changes for the panel: its slider is min 0.5, max 2.4, and
both ends stay inside the clamp.
"""

import pytest

from services.mech.mech_evolutions import (
    get_evolution_config_service, get_evolution_level_info)

# The range the comment on set_difficulty_multiplier promises, stated here so
# the test says what is expected instead of asking the code.
LEVEL_2_COST_FLOOR, LEVEL_2_COST_CEILING = 5.0, 50.0

# What app/templates/_advanced_settings_modal.html offers.
PANEL_MIN, PANEL_MAX = 0.5, 2.4


@pytest.fixture
def service(monkeypatch):
    """The real config, without writing anything to disk."""
    service = get_evolution_config_service()
    saved = {}
    monkeypatch.setattr(service, "save_config",
                        lambda config: saved.update(config) or True)
    service._saved = saved
    return service


def _level_2_cost(multiplier):
    return get_evolution_level_info(2).base_cost * multiplier


def test_the_hardest_setting_reaches_the_promised_ceiling(service):
    service.set_difficulty_multiplier(1000.0)
    applied = service._saved["evolution_settings"]["difficulty_multiplier"]

    assert _level_2_cost(applied) == pytest.approx(LEVEL_2_COST_CEILING), (
        f"the comment promises up to ${LEVEL_2_COST_CEILING}, and the hardest "
        f"setting reaches ${_level_2_cost(applied)}"
    )


def test_the_easiest_setting_stops_at_the_promised_floor(service):
    service.set_difficulty_multiplier(0.0)
    applied = service._saved["evolution_settings"]["difficulty_multiplier"]

    assert _level_2_cost(applied) == pytest.approx(LEVEL_2_COST_FLOOR), (
        f"the comment promises no less than ${LEVEL_2_COST_FLOOR}, and the "
        f"easiest setting goes to ${_level_2_cost(applied)}"
    )


def test_an_ordinary_setting_is_taken_as_it_is(service):
    """Counter-check: a clamp that always clamps would pass the tests above."""
    service.set_difficulty_multiplier(1.3)

    assert service._saved["evolution_settings"]["difficulty_multiplier"] == 1.3


@pytest.mark.parametrize("position", [PANEL_MIN, 1.0, PANEL_MAX])
def test_every_slider_position_survives_the_clamp(service, position):
    """Counter-check: the panel must not be able to send a value the clamp
    silently changes - the operator would see a number that is not in force."""
    service.set_difficulty_multiplier(position)

    assert service._saved["evolution_settings"]["difficulty_multiplier"] == position
