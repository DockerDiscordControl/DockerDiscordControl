#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Regression tests for the expanded mech section in Discord (findings M1 + M3).

Until v2.4.1 `cogs/docker_control.py` did two wrong things when building the
"next evolution" label:

M1  It imported ``MECH_LEVELS`` from ``services.mech.mech_service`` - a name that
    module has never exported. The resulting ImportError escaped the surrounding
    handler (which only catches DiscordException/RuntimeError/OSError/KeyError),
    so pressing the expand button crashed instead of degrading gracefully.

M3  It then resolved the name by comparing a *static* threshold against
    ``mech_cache_result.threshold``, which holds the *dynamic* goal in dollars.
    That comparison practically never matched, so ``next_name`` stayed None and
    levels 1-9 displayed "MAX EVOLUTION REACHED!".

The existing suite missed both because it only exercised the failure path, which
returns earlier. These tests pin the source shape *and* the behaviour of the
helper the fixed code relies on.
"""

from pathlib import Path

import pytest

from services.mech.mech_service_adapter import get_level_name

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE = (PROJECT_ROOT / "cogs" / "docker_control.py").read_text(encoding="utf-8")

MAX_LEVEL = 11


# ---------------------------------------------------------------------------
# M1 - the import must not come back
# ---------------------------------------------------------------------------

class TestBrokenImportIsGone:
    def test_mech_levels_is_never_imported(self):
        """services.mech.mech_service does not export MECH_LEVELS - importing it crashes."""
        assert "import MECH_LEVELS" not in SOURCE
        assert "from services.mech.mech_service import MECH_LEVELS" not in SOURCE

    def test_mech_service_really_does_not_export_it(self):
        """Guard the assumption itself: if the module ever gains the name, this test tells us."""
        import services.mech.mech_service as mech_service

        assert not hasattr(mech_service, "MECH_LEVELS"), \
            "MECH_LEVELS exists now - revisit whether the lookup should use it"

    def test_the_helper_that_replaced_it_is_used(self):
        assert "from services.mech.mech_service_adapter import get_level_name" in SOURCE
        assert "get_level_name(mech_cache_result.level + 1)" in SOURCE


# ---------------------------------------------------------------------------
# M3 - the name must come from the level, not from a threshold comparison
# ---------------------------------------------------------------------------

class TestNoThresholdComparison:
    def test_static_threshold_equality_is_gone(self):
        """The dynamic goal is a dollar amount; comparing it to a static threshold never matched."""
        assert "level_info.threshold == mech_cache_result.threshold" not in SOURCE

    def test_level_10_keeps_its_corrupted_label(self):
        """Deliberate easter egg for the step into the final evolution - must survive the fix."""
        assert 'next_name = "ERR#R: [DATA_C0RR*PTED]"' in SOURCE

    def test_level_11_still_yields_no_next_name(self):
        """Level 11 is the maximum; the UI shows "MAX EVOLUTION REACHED!" when next_name is None."""
        assert "mech_cache_result.level < 10" in SOURCE
        assert "mech_cache_result.level == 10" in SOURCE


# ---------------------------------------------------------------------------
# The helper the fix depends on
# ---------------------------------------------------------------------------

class TestLevelNameLookup:
    @pytest.mark.parametrize("level", range(1, MAX_LEVEL + 1))
    def test_every_real_level_has_a_name(self, level):
        name = get_level_name(level)
        assert name and not name.startswith("Level "), \
            f"level {level} fell back to a placeholder instead of its configured name"

    def test_names_are_distinct_per_level(self):
        """A shared name would make the "next evolution" label meaningless."""
        names = [get_level_name(level) for level in range(1, MAX_LEVEL + 1)]
        assert len(set(names)) == len(names)

    @pytest.mark.parametrize("level", range(1, 10))
    def test_next_level_name_differs_from_the_current_one(self, level):
        """This is exactly what the expanded view shows: current level vs. the one after it."""
        assert get_level_name(level) != get_level_name(level + 1)

    def test_out_of_range_degrades_instead_of_raising(self):
        """Safety net: a future level beyond the config must not crash the expand button."""
        assert get_level_name(MAX_LEVEL + 1) == f"Level {MAX_LEVEL + 1}"
