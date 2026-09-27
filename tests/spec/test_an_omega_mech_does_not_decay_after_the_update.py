# -*- coding: utf-8 -*-
"""An OMEGA mech (level 11) keeps its power across the update to v3.0.

THE FINDING (migration review v2.4.1 -> v3.0, 2026-09-27): v2.4.1 computed
the decay from the table for the mech's CURRENT level
(v2.4.1 services/mech/progress_service.py:798, decay_per_day(snap.level)), and
the table says 0 for level 11. The rate stored in the snapshot was only ever
set by set_new_goal_for_next_level, which the climb to 11 never reaches
(`if snap.level < 11`) - so every OMEGA snapshot written by v2.4.1 still holds
level 10's 200 cents a day. v3.0 decays at the STORED rate (progress_service
current_power_cents), which is right for everything v3.0 writes and turned an
immortal mech holding $300 into $120 after 90 days - on the first start after
the update, with no donation, no event, nothing the operator did.

WHAT HOLDS NOW: load_snapshot puts the table's rate into a final-level
snapshot. For a v2.4.1 OMEGA mech the power shown is exactly what v2.4.1
showed. Below the final level nothing is touched: there the stored rate is
the one the span was measured at (see current_power_cents).

HOW THIS TEST CAN FAIL: the OMEGA mech loses power after loading; the repair
is only in memory (the file keeps 200); a level-10 snapshot's rate is changed.

COUNTER-CHECK (2026-09-27): with the repair in load_snapshot removed, the
OMEGA case went red with 12000 instead of 30000 cents.
"""

import importlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ps(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    reset_progress_runtime()
    clear_progress_paths_cache()
    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module.reset_progress_services()
    # The decay table DDC ships: 200 cents a day at level 10, 0 at level 11.
    (tmp_path / "ddc_config" / "mech").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "services" / "mech" / "defaults" / "decay.json",
                tmp_path / "ddc_config" / "mech" / "decay.json")
    module._decay_config_cache["data"] = None
    module._decay_config_cache["last_load"] = 0
    yield module
    module.reset_progress_services()
    reset_progress_runtime()
    clear_progress_paths_cache()


def _snapshot_as_v241_left_it(ps, level, stored_rate, days_ago):
    anchor = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    raw = {"mech_id": "main", "level": level, "evo_acc": 150000, "power_acc": 30000,
           "goal_requirement": 0, "difficulty_bin": 1, "goal_started_at": anchor,
           "last_decay_day": "", "power_decay_per_day": stored_rate, "version": 0,
           "last_event_seq": 7, "mech_type": "default", "last_user_count_sample": 12,
           "cumulative_donations_cents": 150000}
    path = ps.snapshot_path("main")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_an_omega_mech_keeps_its_power(ps):
    path = _snapshot_as_v241_left_it(ps, level=11, stored_rate=200, days_ago=90)
    assert ps.decay_per_day(11) == 0, "the shipped table changed - this test needs a new premise"

    snap = ps.load_snapshot("main")

    assert ps.current_power_cents(snap) == 30000, "the OMEGA mech lost power by being updated"
    assert json.loads(path.read_text())["power_decay_per_day"] == 0, "repaired in memory only"


def test_below_the_final_level_the_stored_rate_stays(ps):
    path = _snapshot_as_v241_left_it(ps, level=10, stored_rate=200, days_ago=30)
    snap = ps.load_snapshot("main")
    assert snap.power_decay_per_day == 200
    assert ps.current_power_cents(snap) == 30000 - 30 * 200
    assert json.loads(path.read_text())["power_decay_per_day"] == 200
