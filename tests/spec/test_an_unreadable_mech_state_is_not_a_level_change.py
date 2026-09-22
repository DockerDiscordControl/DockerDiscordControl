# -*- coding: utf-8 -*-
"""A mech state that could not be read is not a level change.

THE FINDING: the overview loop asks the mech cache for the current level and
power, and on failure set both to ZERO. Zero is a value: with a channel that
last saw level 5, "power <= 0" fired (power depleted) and "|0 - 5| >= 1"
fired (level changed), so the loop deleted and reposted the overview - and
wrote 0 into last_glvl_per_channel and into mech_state.json. The next
successful cycle then saw 5 against 0 and did it all again. One read error
cost two delete-and-repost rounds and left a wrong level on disk.

Unknown is not zero: a cycle that could not read the state changes nothing.

COUNTER-CHECK (2026-09-22): red before - the unknown state reported a level
change and a depleted power. A real change and a real depletion must still be
reported (the other tests).
"""

import pytest

from cogs.message_updates import mech_change


def test_an_unknown_state_changes_nothing():
    changed, depleted, new_last = mech_change(None, None, last_glvl=5)

    assert (changed, depleted) == (False, False)
    assert new_last is None, "the unknown state must not be written anywhere"


def test_a_real_level_change_is_reported():
    """Counter-check: the thing this code is for."""
    changed, depleted, new_last = mech_change(6, 12.0, last_glvl=5)

    assert changed is True and new_last == 6


def test_real_power_depletion_is_reported():
    """Counter-check, the other trigger."""
    _changed, depleted, _new_last = mech_change(5, 0.0, last_glvl=5)

    assert depleted is True


def test_the_first_cycle_learns_the_level():
    """Unchanged behaviour: a channel with nothing tracked yet counts as a change
    (it did before this was extracted, and that is not what this finding is
    about) - and the level is remembered."""
    changed, depleted, new_last = mech_change(5, 10.0, last_glvl=0)

    assert changed is True and depleted is False and new_last == 5


def test_an_unchanged_level_does_nothing():
    """Counter-check: no recreate while nothing moves."""
    assert mech_change(5, 10.0, last_glvl=5) == (False, False, None)
