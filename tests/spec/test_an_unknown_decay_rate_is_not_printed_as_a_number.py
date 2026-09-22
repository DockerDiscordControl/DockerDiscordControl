# -*- coding: utf-8 -*-
"""A decay rate nobody looked up is not printed as if it had been measured.

THE FINDING: the expanded overview prints the mech's power consumption from
get_evolution_level_info(level).decay_per_day, and falls back to 1.0 when
that lookup returns nothing - a level outside the table, a table that could
not be read. The line then reads "Power Consumption: 🔻 1.0 per day", a
number that was never computed and that no reader can tell from a real one.
The honest branch is already there one line above: "No decay" for a rate of
zero.

An unknown rate now says it is unknown.

COUNTER-CHECK (2026-09-22): red before - the unknown level printed 1.0. A
known level must still print its real rate (second test).
"""

import pytest

from cogs.overview_embeds import power_consumption_line


def test_an_unknown_level_says_unknown():
    line = power_consumption_line(None)

    assert "1.0" not in line
    assert "?" in line or "unknown" in line.lower(), line


def test_a_known_rate_is_printed():
    """Counter-check: the measured rate is still shown."""
    line = power_consumption_line(2.5)

    assert "2.5" in line


def test_no_decay_stays_no_decay():
    """Counter-check, the other side: zero has its own wording."""
    assert "decay" in power_consumption_line(0).lower()
