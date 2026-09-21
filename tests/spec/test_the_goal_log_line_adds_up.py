# -*- coding: utf-8 -*-
"""What the log says a level costs is what it costs.

THE FINDING (review D27, pass 2, section 24 F3):
`set_new_goal_for_next_level` prices the next level with

    req = requirement_for_level_and_bin(snap.level, b, member_count=user_count)

which computes the dynamic part from the PRECISE member formula - the first
ten members free, ten cents each after that. The log line two lines below
then computed a SECOND dynamic cost, straight from the old bin table::

    dynamic_cost = int(CFG.get("bin_to_dynamic_cost", {}).get(str(b), 0))
    logger.info(f"... requirement=${req} (${base_cost} base + ${dynamic_cost} dynamic ...")

The two formulas disagree in the normal case. With eleven members the precise
dynamic part is $0.10, so the requirement is $40.10 - while bin 1's table
says $4.00, and the line reads

    requirement=$40.10 ($40.00 base + $4.00 dynamic, bin=1, users=11)

an arithmetic breakdown that does not add up to its own total.

The price itself was never wrong. What was wrong is the one line an operator
reads to find out WHY a level costs what it costs - and this is the mech, so
the question is about money people donated.

The dynamic part now has one definition, `dynamic_cost_cents`, which both the
pricing and the log line use. Two numbers that must agree are not computed
twice any more.

The second test is the counter-case: the free tier must still read as $0.00,
or "always use the bin table" would satisfy the first test.
"""

import importlib
import json
import logging
import re
from types import SimpleNamespace

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache

# "requirement=$40.10 ($40.00 base + $4.00 dynamic, bin=1, users=11)"
LINE = re.compile(r"requirement=\$(?P<total>[\d.]+) \(\$(?P<base>[\d.]+) base \+ "
                  r"\$(?P<dynamic>[\d.]+)")


@pytest.fixture
def progress(tmp_path, monkeypatch):
    """A mech whose bin table and member formula deliberately disagree."""
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "config"))
    reset_progress_runtime()
    clear_progress_paths_cache()

    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module.reset_progress_services()
    config = {"timezone": "UTC", "difficulty_bins": [0, 50],
              "level_base_costs": {str(level): 4000 for level in range(1, 12)},
              # $4.00 for every bin - the old table, which the precise formula
              # agrees with only by accident.
              "bin_to_dynamic_cost": {str(b): 400 for b in range(1, 22)},
              "mech_power_decay_per_day": {"default": 0}}
    module.runtime.configure_defaults(config)
    module.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    module.CFG = module.runtime.load_config(refresh=True)
    module.TZ = module.runtime.timezone(refresh=True)
    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(config_module, "get_config_service",
                        lambda: SimpleNamespace(
                            get_evolution_mode_service=lambda request:
                            config_module.GetEvolutionModeResult(
                                success=True, use_dynamic=True,
                                difficulty_multiplier=1.0)),
                        raising=False)
    module._decay_config_cache["data"] = None
    module._decay_config_cache["last_load"] = 0
    try:
        yield module
    finally:
        module.reset_progress_services()
        reset_progress_runtime()
        clear_progress_paths_cache()


def _goal_line(progress, caplog, *, members):
    with progress.LOCK:
        snap = progress.load_snapshot("main")
    # Creating the snapshot sets a first goal and logs its own line (users=0).
    # Reading the first match instead of this call's would test the wrong line -
    # which is exactly what happened on the first run of this file.
    caplog.clear()
    with caplog.at_level(logging.INFO):
        progress.set_new_goal_for_next_level(snap, members)
    for record in caplog.records:
        hit = LINE.search(record.getMessage())
        if hit:
            return hit, snap
    pytest.fail("no goal line was logged at all - the test no longer reads "
                f"what the code writes: {[r.getMessage() for r in caplog.records]}")


def test_the_breakdown_adds_up_to_the_requirement(progress, caplog):
    """Eleven members: $0.10 dynamic by the formula, $4.00 by the old table."""
    hit, _ = _goal_line(progress, caplog, members=11)

    base, dynamic, total = (float(hit["base"]), float(hit["dynamic"]),
                            float(hit["total"]))
    assert round(base + dynamic, 2) == total, (
        f"the log says ${total:.2f} is ${base:.2f} base plus ${dynamic:.2f} "
        f"dynamic, which comes to ${base + dynamic:.2f}"
    )


@pytest.mark.parametrize("members", [0, 1, 10])
def test_the_free_tier_still_reads_as_nothing(progress, caplog, members):
    """The counter-case: the first ten members are free, and the line says so.

    ``members=0`` is the line a fresh installation writes while the snapshot is
    being created - it claimed $4.00 of dynamic cost for a mech with no members
    at all, and its own total proved that nothing of the sort was charged.
    """
    hit, _ = _goal_line(progress, caplog, members=members)

    assert float(hit["dynamic"]) == 0.0, (
        f"{members} members are free and the line charges ${hit['dynamic']} for them"
    )
    assert round(float(hit["base"]) + float(hit["dynamic"]), 2) == float(hit["total"])


def test_a_level_without_a_configured_base_cost_is_logged_as_it_is_priced(progress, caplog):
    """The base half of the same line.

    The price substitutes $10.00 for a level whose base cost is missing or
    nonsensical; the log line read the configuration raw and would have said
    $0.00 for a level that costs $10.00.
    """
    progress.CFG["level_base_costs"]["1"] = 0

    hit, _ = _goal_line(progress, caplog, members=0)

    assert float(hit["base"]) == 10.0, (
        f"the level is priced at $10.00 by default and the line says "
        f"${hit['base']}"
    )
    assert round(float(hit["base"]) + float(hit["dynamic"]), 2) == float(hit["total"])


def test_the_price_itself_is_unchanged(progress):
    """A pin: this is about the log line, not about what anybody pays."""
    assert progress.requirement_for_level_and_bin(1, 1, member_count=11) == 4010
    assert progress.requirement_for_level_and_bin(1, 1, member_count=10) == 4000
    # Without a member count the bin table is still the fallback.
    assert progress.requirement_for_level_and_bin(1, 1) == 4400


def test_the_goal_that_was_set_is_the_one_that_was_logged(progress, caplog):
    """The line must describe the goal the snapshot actually received."""
    hit, snap = _goal_line(progress, caplog, members=11)

    assert snap.goal_requirement == 4010
    assert float(hit["total"]) == snap.goal_requirement / 100
