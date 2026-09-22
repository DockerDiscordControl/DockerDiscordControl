# -*- coding: utf-8 -*-
"""The mech's maxima are the real ones, not round numbers nobody measured.

Two numbers the operator reads as measurements:

* the cached status publishes glvl_max = 100 beside a glvl that is the
  evolution level, which ends at 11. The log line reads "glvl=3/100", the
  embed and /api/donation/status carry it, and one test's own stub uses 11 -
  the service and its readers disagreed about what the ceiling is;
* at level 11 the power bar's maximum is a hardcoded $1.00: goal_requirement
  is 0 there, so `goal_requirement + 100 if > 0 else 100` falls to 100 cents.
  The Discord log prints "Power=$250.00/$1.00" and the panel divides by it.
  At the final level there is no next goal, so there is no maximum to state -
  it is None, the way every other unknown in this service is.

COUNTER-CHECK (2026-09-22): red before - glvl_max was 100 and the level-11
maximum was 100 cents.
"""

import pytest

from services.mech.mech_evolutions import get_all_evolution_levels
from services.mech.progress_service import Snapshot, compute_ui_state


def test_the_level_maximum_is_the_last_evolution():
    from services.mech.mech_status_cache_service import MechStatusCacheResult

    highest = max(get_all_evolution_levels())

    assert MechStatusCacheResult.glvl_max == highest, (
        f"the service says {MechStatusCacheResult.glvl_max}, the table ends at {highest}")


def _snapshot(level, goal_requirement, power):
    return Snapshot(mech_id="main", level=level, evo_acc=0, power_acc=power,
                    goal_requirement=goal_requirement, difficulty_bin=1,
                    goal_started_at="2026-09-22T00:00:00+00:00", last_decay_day="2026-09-22",
                    power_decay_per_day=0, version=1, mech_type="default",
                    last_user_count_sample=0, cumulative_donations_cents=power)


def test_the_last_level_states_no_power_maximum():
    state = compute_ui_state(_snapshot(level=11, goal_requirement=0, power=25000))

    assert state.power_max is None, (
        f"the final level reports a maximum of {state.power_max}, which nobody computed")


def test_an_ordinary_level_still_has_its_maximum():
    """Counter-check: the number that IS computed must stay."""
    state = compute_ui_state(_snapshot(level=3, goal_requirement=1000, power=400))

    assert state.power_max == 11.0        # goal + $1, in dollars
