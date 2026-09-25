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
returns earlier. These tests pinned the source shape *and* the behaviour of the
helper the fixed code relies on.

THE SOURCE SHAPE HAS NO SUBJECT ANY MORE (2026-09-25). Both findings lived in
``_create_overview_embed_expanded``, the old shape of the status channel
overview, which was removed because no posted view could reach it
(tests/spec/test_a_registered_button_is_on_a_posted_view.py). The three cases
that quoted its lines went with it; the two NEGATIVE cases stay, because
"this import must not come back" is a rule the whole cog still has to keep.

WHAT WENT WITH IT, noted so nobody looks for it: the level-10 easter egg
``ERR#R: [DATA_C0RR*PTED]``. It was only ever rendered by that builder, so
the operator could not have seen it since the overview changed shape. The
live path (services/mech/mech_evolutions.get_evolution_progress, shown in the
private Mech panel) simply names the next evolution. Putting the egg back is
a decision, not a repair.

WHAT REMAINS BELOW is the behaviour of ``get_level_name`` itself, which the
private panel and the web donation status both rely on.
"""

from pathlib import Path

import pytest

from services.mech.mech_service_adapter import get_level_name

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# The cog spans several files since the Phase 3 split; the expanded overview
# (where the mech names are built) moved to overview_embeds.py.
SOURCE = "\n".join(
    (PROJECT_ROOT / "cogs" / name).read_text(encoding="utf-8")
    for name in ("docker_control.py", "overview_embeds.py")
)

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


# ---------------------------------------------------------------------------
# M3 - the name must come from the level, not from a threshold comparison
# ---------------------------------------------------------------------------

class TestNoThresholdComparison:
    def test_static_threshold_equality_is_gone(self):
        """The dynamic goal is a dollar amount; comparing it to a static threshold never matched."""
        assert "level_info.threshold == mech_cache_result.threshold" not in SOURCE


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
        """This is what the private Mech panel shows: the current level and the
        one after it (the operator's screenshot: "The Abyss Engine (Level 6)"
        above, "The Rift Strider" as the next)."""
        assert get_level_name(level) != get_level_name(level + 1)

    def test_out_of_range_degrades_instead_of_raising(self):
        """Safety net: a future level beyond the config must not crash the panel."""
        assert get_level_name(MAX_LEVEL + 1) == f"Level {MAX_LEVEL + 1}"
