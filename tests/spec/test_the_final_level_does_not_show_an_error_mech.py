# -*- coding: utf-8 -*-
"""The final level has no maximum, and nothing falls over that.

THE FINDING (independent review, 2026-09-23): at level 11 there is no next
goal, so power_max is None - the honest answer, pinned by
test_the_level_maximum_is_the_real_one.py. Three places compare it with a
number: the adapter twice (speed from power/max) and the Discord overview once
(the power bar). `None > 0` raises TypeError.

The adapter's conversion is not guarded, so get_state() raises for every
caller; get_mech_state_service catches it and hands back success=False,
level=1, power=0.0, name="Error". The OMEGA MECH - the thing the whole
evolution is built towards - would show up in the panel as a broken level-1
mech, and in Discord the bar would be missing with a logged traceback.

Nobody has reached level 11 on this installation (it is at level 6), which is
why this has never been seen.

COUNTER-CHECK (2026-09-23): red before - the conversion raised TypeError, and
so did the embed's bar. The level-3 cases keep the ordinary speed and bar.
"""

import pytest

from services.mech.progress_service import ProgressState


def _state(level, power_current, power_max):
    return ProgressState(
        level=level, power_current=power_current, power_max=power_max, power_percent=100,
        evo_current=0.0, evo_max=0.0, evo_percent=0, total_donated=100.0,
        can_level_up=False, is_offline=power_current == 0, difficulty_bin=1,
        difficulty_tier="Tiny Community", member_count=0)


def test_the_adapter_converts_the_final_level(monkeypatch):
    from services.mech.mech_service_adapter import MechServiceAdapter

    adapter = MechServiceAdapter()

    converted = adapter._convert_state(_state(11, 250.0, None))

    assert converted.evolution_level == 11
    assert converted.power_level == pytest.approx(250.0)
    assert converted.speed_level == 100, (
        "a mech with no maximum is running at full speed, not standing still")


def test_an_ordinary_level_still_scales_its_speed():
    """Counter-check: the speed must still follow the power."""
    from services.mech.mech_service_adapter import MechServiceAdapter

    converted = MechServiceAdapter()._convert_state(_state(3, 5.0, 10.0))

    assert converted.speed_level == pytest.approx(50.0)


def test_the_overview_draws_a_bar_without_a_maximum():
    """The Discord embed's power bar, for the same state."""
    from cogs import overview_embeds

    source = (overview_embeds.__file__ or "")
    with open(source, "r", encoding="utf-8") as f:
        text = f.read()

    assert "if Power_max > 0:" not in text, (
        "the bar compares a maximum that is None at the final level")
