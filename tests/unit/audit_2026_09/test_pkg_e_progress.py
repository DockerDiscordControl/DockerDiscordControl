# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Audit 2026-09 Package E regression tests       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Package E (mech & donations): progress service regressions.

E1 decay debt / is_offline / rebuild consistency (+ old-snapshot continuity),
E2 cents rounding, E3 admin reset snapshot, E4 member count for level-up goals,
E7 corrupt event lines and corrupt snapshots.

All state lives in tmp_path (DDC_PROGRESS_DATA_DIR / DDC_CONFIG_DIR).
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache

# Level-1 goal of $1000 so ordinary test donations never level up by accident
BASE_COST = 100000


@pytest.fixture
def ps(tmp_path, monkeypatch):
    """Reloaded progress_service with isolated paths and dynamic difficulty."""
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(tmp_path / "progress"))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path / "ddc_config"))
    reset_progress_runtime()
    clear_progress_paths_cache()

    module = importlib.reload(importlib.import_module("services.mech.progress_service"))
    module.reset_progress_services()
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
    module._decay_config_cache["data"] = None  # no decay.json -> default 100 cents/day
    module._decay_config_cache["last_load"] = 0

    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(
        config_module,
        "get_config_service",
        lambda: SimpleNamespace(
            get_evolution_mode_service=lambda request: config_module.GetEvolutionModeResult(
                success=True, use_dynamic=True, difficulty_multiplier=1.0,
            )
        ),
        raising=False,
    )

    yield module

    module.reset_progress_services()
    reset_progress_runtime()
    clear_progress_paths_cache()


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _write_old_format_snapshot(ps, mech_id: str, **overrides) -> dict:
    """Write a snapshot exactly as the pre-fix code did (no power_decay_since)."""
    data = {
        "mech_id": mech_id,
        "level": 2,
        "evo_acc": 0,
        "power_acc": 0,
        "goal_requirement": 5000,
        "difficulty_bin": 1,
        "goal_started_at": _ago(1),
        "last_decay_day": "2026-09-01",
        "power_decay_per_day": 100,
        "version": 3,
        "last_event_seq": 0,
        "mech_type": "default",
        "last_user_count_sample": 0,
        "cumulative_donations_cents": 2500,
    }
    data.update(overrides)
    path = ps.snapshot_path(mech_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _old_displayed_power_cents(data: dict) -> int:
    """The pre-fix compute_ui_state formula (decay from goal_started_at, errors -> no decay)."""
    try:
        started = datetime.fromisoformat(data["goal_started_at"].replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return max(0, data["power_acc"] - int((elapsed / 86400.0) * 100))
    except (ValueError, TypeError):
        return data["power_acc"]


# ---------------------------------------------------------------------------
# E1 - decay is settled on power changes; old snapshots keep their power
# ---------------------------------------------------------------------------

def test_e1_old_snapshot_displayed_power_unchanged_on_first_load(ps):
    data = _write_old_format_snapshot(ps, "cont", power_acc=750, goal_started_at=_ago(1.5), evo_acc=1200)
    expected = _old_displayed_power_cents(data)
    assert expected == 600  # 750 - 1.5 days * 100

    state = ps.ProgressService("cont").get_state()

    assert state.power_current == pytest.approx(expected / 100.0, abs=0.011)
    assert state.level == 2
    assert state.evo_current == pytest.approx(12.0)
    assert state.total_donated == pytest.approx(25.0)
    # goal_started_at stays the decay anchor; no extra key (v2.3.1 must load the file)
    persisted = json.loads(ps.snapshot_path("cont").read_text(encoding="utf-8"))
    assert persisted["goal_started_at"] == data["goal_started_at"]
    assert "power_decay_since" not in persisted
    assert persisted["power_acc"] == 750


def test_e1_old_snapshot_with_naive_timestamp_does_not_jump(ps):
    # Written by the old admin reset: naive datetime -> old code applied no decay at all
    _write_old_format_snapshot(ps, "naive", power_acc=300, goal_started_at="2026-09-01T12:00:00.123456")

    state = ps.ProgressService("naive").get_state()

    assert state.power_current == pytest.approx(3.0)
    snap = ps.load_snapshot("naive")
    # Decay clock starts now (aware UTC) instead of decaying 2 weeks at once
    assert datetime.fromisoformat(snap.goal_started_at).tzinfo is not None


def test_e1_old_snapshot_with_unknown_keys_loads(ps):
    _write_old_format_snapshot(ps, "extra", power_acc=100, goal_started_at=_ago(0), future_field="x")
    snap = ps.load_snapshot("extra")
    assert snap.level == 2
    assert snap.power_acc == 100


def test_e1_donation_adds_to_current_power_not_decay_debt(ps):
    # Level 2, goal set 20 days ago, $10 power -> displays $0 (20 days * $1 decay)
    _write_old_format_snapshot(ps, "debt", power_acc=1000, goal_started_at=_ago(20))
    svc = ps.ProgressService("debt")
    before = svc.get_state()
    assert before.power_current == 0.0  # continuity: still $0 on first load

    state = svc.add_donation(10.0, donor="helper")

    # Old code: max(0, 2000 - 2000) = 0 -> mech stayed offline despite the donation
    assert state.level == 2  # no level-up ($10 < $50 goal)
    assert state.power_current == pytest.approx(10.0, abs=0.011)
    assert state.is_offline is False
    snap = ps.load_snapshot("debt")
    assert snap.power_acc == 1000  # debt settled (clamped at 0) before adding


def test_e1_is_offline_matches_displayed_power(ps):
    snap = ps.Snapshot(mech_id="off", level=2, power_acc=500, goal_requirement=5000,
                       goal_started_at=_ago(10))
    state = ps.compute_ui_state(snap)
    assert state.power_current == 0.0
    assert state.is_offline is True  # old code: power_acc == 0 -> False


def test_e1_power_gift_uses_decayed_power(ps):
    _write_old_format_snapshot(ps, "gift", power_acc=400, goal_started_at=_ago(30))
    svc = ps.ProgressService("gift")

    state, gift = svc.power_gift("campaign-e1")

    # Displayed power was $0, so the monthly gift is granted (old code: raw 400 > 0 -> skipped)
    assert gift is not None
    assert state.power_current == pytest.approx(gift, abs=0.011)


def test_e1_rebuild_matches_live_path(ps):
    """Admin delete/restore (rebuild) must not make the displayed power jump."""
    # First donation $5 twenty days ago (event + snapshot as the old code left them)
    first = ps.Event(seq=ps.next_seq(), ts=_ago(20), type="DonationAdded", mech_id="rb",
                     payload={"donation_id": "a", "idempotency_key": "first", "units": 500,
                              "donor": "early", "channel_id": None})
    ps.append_event(first)
    _write_old_format_snapshot(ps, "rb", level=1, power_acc=500, evo_acc=500, goal_requirement=BASE_COST,
                               goal_started_at=first.ts, cumulative_donations_cents=500,
                               last_event_seq=first.seq)
    svc = ps.ProgressService("rb")

    live = svc.add_donation(10.0, donor="late", idempotency_key="second")
    rebuilt = svc.rebuild_from_events()

    assert live.power_current == pytest.approx(10.0, abs=0.011)
    assert rebuilt.power_current == pytest.approx(live.power_current, abs=0.011)
    assert rebuilt.level == live.level == 1
    assert rebuilt.is_offline is live.is_offline is False
    assert rebuilt.total_donated == pytest.approx(live.total_donated)


def test_e1_rebuild_sets_decay_anchor_to_last_event(ps):
    svc = ps.ProgressService("anchor")
    svc.add_donation(3.0, idempotency_key="k")
    svc.rebuild_from_events()
    snap = ps.load_snapshot("anchor")
    last_ts = max(e.ts for e in ps.read_events() if e.mech_id == "anchor")
    assert snap.goal_started_at == last_ts


# ---------------------------------------------------------------------------
# E2 - cents are not truncated
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("amount, cents", [(19.99, 1999), (10.75, 1075), (0.5, 50), (0.29, 29)])
def test_e2_add_donation_rounds_to_cents(ps, amount, cents):
    svc = ps.ProgressService(f"cents-{cents}")
    svc.add_donation(amount, idempotency_key=f"c{cents}")
    evt = next(e for e in ps.read_events() if e.mech_id == f"cents-{cents}" and e.type == "DonationAdded")
    assert evt.payload["units"] == cents


# ---------------------------------------------------------------------------
# E3 - admin reset writes an aware timestamp and the real level-1 goal
# ---------------------------------------------------------------------------

def test_e3_reset_snapshot_is_aware_and_uses_real_level1_goal(ps):
    reset_module = importlib.import_module("services.donation.unified.reset")
    snap = ps.load_snapshot("main")
    snap.last_user_count_sample = 120
    snap.level = 4
    ps.persist_snapshot(snap)

    reset_module._write_fresh_snapshot(ps.runtime.paths)

    data = json.loads(ps.snapshot_path("main").read_text(encoding="utf-8"))
    assert datetime.fromisoformat(data["goal_started_at"]).tzinfo is not None
    assert "power_decay_since" not in data
    expected_goal = ps.requirement_for_level_and_bin(1, ps.current_bin(120), member_count=120)
    assert data["goal_requirement"] == expected_goal != 400
    assert data["level"] == 1 and data["power_acc"] == 0
    assert data["last_user_count_sample"] == 120

    # Decay works after a reset (the naive timestamp raised TypeError -> decay stopped)
    fresh = ps.load_snapshot("main")
    fresh.power_acc = 500
    fresh.goal_started_at = _ago(2)
    assert ps.compute_ui_state(fresh).power_current == pytest.approx(3.0, abs=0.011)


# ---------------------------------------------------------------------------
# E4 - level-up goal uses the latest member count, not the startup file
# ---------------------------------------------------------------------------

def test_e4_level_up_goal_uses_latest_member_count_sample(ps):
    ps.MEMBER_COUNT_FILE.write_text(json.dumps({"count": 30}), encoding="utf-8")  # bot startup value
    svc = ps.ProgressService("mc")
    svc.update_member_count(400)  # published later (e.g. Discord donation)

    state = svc.add_donation(BASE_COST / 100.0, idempotency_key="lvl")

    assert state.level == 2
    snap = ps.load_snapshot("mc")
    assert snap.goal_requirement == ps.requirement_for_level_and_bin(2, ps.current_bin(400), member_count=400)
    assert snap.last_user_count_sample == 400


def test_e4_member_count_file_is_fallback(ps):
    # Without a published sample the file wins (G5/R1-7: newest source, see test_r2_g5_mech)
    assert ps.member_count_for_goal(ps.Snapshot(mech_id="x", last_user_count_sample=77)) == 77
    ps.MEMBER_COUNT_FILE.write_text(json.dumps({"count": 30}), encoding="utf-8")
    assert ps.member_count_for_goal(ps.Snapshot(mech_id="x", last_user_count_sample=0)) == 30
    assert ps.member_count_for_goal(ps.Snapshot(mech_id="x", last_user_count_sample=77)) == 30


# ---------------------------------------------------------------------------
# E7 - corrupt event lines / corrupt snapshot
# ---------------------------------------------------------------------------

def test_e7_truncated_event_line_does_not_block_donations(ps):
    svc = ps.ProgressService("trunc")
    svc.add_donation(1.0, idempotency_key="before")
    # Crash during append: truncated last line without trailing newline
    with open(ps.EVENT_LOG, "a", encoding="utf-8") as f:
        f.write('{"seq": 99, "ts": "2026-09-1')

    state = svc.add_donation(2.0, idempotency_key="after")  # raised JSONDecodeError before

    assert state.total_donated == pytest.approx(3.0)
    donations = [e for e in ps.read_events() if e.mech_id == "trunc" and e.type == "DonationAdded"]
    # The new event was written on its own line, not glued onto the damaged one
    assert [e.payload["idempotency_key"] for e in donations] == ["before", "after"]


def test_e7_corrupt_snapshot_is_rebuilt_from_events(ps):
    svc = ps.ProgressService("corrupt")
    svc.add_donation(5.0, idempotency_key="a")
    svc.add_donation(2.5, idempotency_key="b")
    path = ps.snapshot_path("corrupt")
    path.write_text('{"mech_id": "corrupt", "level": 1, "evo_', encoding="utf-8")

    snap = ps.load_snapshot("corrupt")

    # Old code silently reset to an empty level-1 mech
    assert snap.cumulative_donations_cents == 750
    assert snap.evo_acc == 750
    backups = list(path.parent.glob("corrupt.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8").startswith('{"mech_id": "corrupt"')
