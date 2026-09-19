# -*- coding: utf-8 -*-
# @covers Z1
"""Z1 - a corrupt snapshot next to a damaged event log does not reset the mech.

THE FINDING (stage 4 review pass 1, section 24 F3, re-checked 2026-09-19): a
snapshot that fails to decode is moved aside and rebuilt from the event log.
But rebuild_from_events REFUSES to rebuild from a log with unreadable lines -
rightly, when it would replace a good snapshot with an incomplete replay. In
the recovery there IS no good snapshot any more (it was just moved aside), so
the refusal left nothing, and the mech started over at level 1 with no
donations. A double fault, logged at ERROR, the corrupt file kept - but the
readable part of the ledger was thrown away.

THE RULE NOW: only the recovery of a corrupt snapshot may rebuild from a
damaged log - the readable events are the best state there is. Everywhere
else the refusal stands (checked below).
"""

import importlib
import json
from types import SimpleNamespace

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache

BASE_COST = 100000  # $1,000 per level - small donations never level up here


@pytest.fixture
def ps(tmp_path, monkeypatch):
    """Reloaded progress_service with isolated paths (as in test_pkg_e_progress.py)."""
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module._progress_service = None
    config = {
        "timezone": "UTC",
        "difficulty_bins": [0, 50],
        "level_base_costs": {str(level): BASE_COST for level in range(1, 12)},
        "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
        "mech_power_decay_per_day": {"default": 100},
    }
    module.runtime.configure_defaults(config)
    module.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    module.CFG = module.runtime.load_config(refresh=True)
    module.TZ = module.runtime.timezone(refresh=True)
    module._decay_config_cache["data"] = None
    module._decay_config_cache["last_load"] = 0
    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(
        config_module, "get_config_service",
        lambda: SimpleNamespace(get_evolution_mode_service=lambda request:
                                config_module.GetEvolutionModeResult(
                                    success=True, use_dynamic=True, difficulty_multiplier=1.0)),
        raising=False)
    yield module
    module._progress_service = None
    reset_progress_runtime()
    clear_progress_paths_cache()


def _ledger_with_a_damaged_line(ps, mech):
    svc = ps.ProgressService(mech)
    svc.add_donation(10.0, "Alex", idempotency_key="k1")
    svc.add_donation(5.0, "Sam", idempotency_key="k2")
    with open(ps.EVENT_LOG, "a", encoding="utf-8") as f:
        f.write('{"seq": 99, "type": "DonationAdd\n')      # a line cut off mid-write
    return svc


def test_a_corrupt_snapshot_is_rebuilt_from_the_readable_events(ps):
    _ledger_with_a_damaged_line(ps, "m1")
    ps.snapshot_path("m1").write_text("{broken", encoding="utf-8")

    snap = ps.load_snapshot("m1")

    assert snap.cumulative_donations_cents == 1500, (
        f"the mech restarted with {snap.cumulative_donations_cents} cents although the "
        f"ledger still holds two readable donations ($15)"
    )


def test_a_good_snapshot_is_still_not_replaced_from_a_damaged_log(ps):
    """Guard: the refusal must stay where a good snapshot exists."""
    svc = _ledger_with_a_damaged_line(ps, "m2")
    path = ps.snapshot_path("m2")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["cumulative_donations_cents"] = 9999          # something only the snapshot knows
    path.write_text(json.dumps(data), encoding="utf-8")

    svc.rebuild_from_events()

    assert ps.load_snapshot("m2").cumulative_donations_cents == 9999, \
        "a good snapshot was replaced by a replay of a damaged log"
