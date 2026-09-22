# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Audit 2026-09 round 2, package G5 (mech)       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Package G5 (mech) regression tests.

R1-8  snapshot schema stays identical to v2.3.1 (downgrade safety); the pre-release
      ``power_decay_since`` key is migrated without changing the displayed power.
R5-4  rebuild_from_events gives the same state as the live path (exact-hit bonus,
      system donations, decay settlement, level goals), incl. a randomized check.
R1-7  the startup member-count step no longer writes a stale snapshot copy back;
      member_count_for_goal uses the newest source (event vs member_count.json).

All state lives in tmp_path (DDC_PROGRESS_DATA_DIR / DDC_CONFIG_DIR); a frozen clock
makes the decay arithmetic exact.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import random
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache

LEVEL_COSTS = {str(level): 200 + 100 * level for level in range(1, 12)}  # level 1 goal: $3.00
FIELDS = ("level", "evo_acc", "power_acc", "goal_requirement", "difficulty_bin", "goal_started_at",
          "power_decay_per_day", "last_user_count_sample", "cumulative_donations_cents")


# v2.3.1 (commit d8f10ae) Snapshot model and loader, verbatim from
# `git show d8f10ae:services/mech/progress_service.py`
@dataclass
class HeadSnapshot:
    mech_id: str
    level: int = 1
    evo_acc: int = 0  # Evolution accumulator (cents)
    power_acc: int = 0  # Power accumulator (cents)
    goal_requirement: int = 0  # Requirement for next level (cents)
    difficulty_bin: int = 1
    goal_started_at: str = ""
    last_decay_day: str = ""  # YYYY-MM-DD (local)
    power_decay_per_day: int = 100  # cents
    version: int = 0
    last_event_seq: int = 0
    mech_type: str = "default"
    last_user_count_sample: int = 0
    cumulative_donations_cents: int = 0  # Total donations ever (never resets)

    @staticmethod
    def from_json(d):
        return HeadSnapshot(**d)


def _head_displayed_power_cents(data: dict, now: datetime, dpp: int = 100) -> int:
    """v2.3.1 compute_ui_state: decay from goal_started_at, errors -> no decay."""
    power = data["power_acc"]
    if data["goal_started_at"]:
        try:
            goal_time = datetime.fromisoformat(data["goal_started_at"].replace("Z", "+00:00"))
            elapsed = (now - goal_time).total_seconds()
            power = max(0, data["power_acc"] - int((elapsed / 86400.0) * dpp))
        except (ValueError, TypeError):
            pass
    return power


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
        "level_base_costs": LEVEL_COSTS,
        "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
        "mech_power_decay_per_day": {"default": 100},
    }
    module.runtime.configure_defaults(config)
    module.runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    module.CFG = module.runtime.load_config(refresh=True)
    module.TZ = module.runtime.timezone(refresh=True)
    # Uniform 100 cents/day, stated explicitly: these tests are about migration, not
    # decay rates. They used to rely on decay.json being ABSENT - since the mech data
    # ships as defaults (services/mech/defaults/decay.json: 150 cents at level 7),
    # "absent" no longer means 100.
    (tmp_path / "ddc_config" / "mech").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ddc_config" / "mech" / "decay.json").write_text(json.dumps({"default": 100}), encoding="utf-8")
    module._decay_config_cache["data"] = None
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


@pytest.fixture
def clock(ps, monkeypatch):
    """Frozen, manually advanced clock for progress_service (``clock.now`` is aware UTC)."""
    state = SimpleNamespace(now=datetime(2026, 9, 15, 20, 0, 0, 123456, tzinfo=timezone.utc))

    class FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return state.now.astimezone(tz) if tz is not None else state.now.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return state.now.replace(tzinfo=None)

    monkeypatch.setattr(ps, "datetime", FrozenDT)
    return state


def _ago(clock, days: float) -> str:
    return (clock.now - timedelta(days=days)).isoformat()


def _write_snapshot(ps, mech_id: str, **overrides) -> dict:
    data = {
        "mech_id": mech_id, "level": 2, "evo_acc": 0, "power_acc": 0, "goal_requirement": 5000,
        "difficulty_bin": 1, "goal_started_at": "", "last_decay_day": "2026-09-01",
        "power_decay_per_day": 100, "version": 3, "last_event_seq": 0, "mech_type": "default",
        "last_user_count_sample": 0, "cumulative_donations_cents": 2500,
    }
    data.update(overrides)
    path = ps.snapshot_path(mech_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _disk(ps, mech_id: str) -> dict:
    return json.loads(ps.snapshot_path(mech_id).read_text(encoding="utf-8"))


def _fields(snap) -> dict:
    return {name: getattr(snap, name) for name in FIELDS}


# ---------------------------------------------------------------------------
# R1-8 - snapshot schema identical to v2.3.1, legacy key migrated
# ---------------------------------------------------------------------------

def test_r1_8_snapshot_fields_match_v231(ps):
    assert {f.name for f in fields(ps.Snapshot)} == {f.name for f in fields(HeadSnapshot)}


def test_r1_8_every_written_snapshot_loads_in_v231(ps, clock):
    head_keys = {f.name for f in fields(HeadSnapshot)}
    svc = ps.ProgressService("main")

    def check():
        data = _disk(ps, "main")
        assert set(data) == head_keys
        HeadSnapshot.from_json(data)  # v2.3.1 raised TypeError on any unknown key

    svc.get_state(); check()
    svc.add_donation(3.0, idempotency_key="exact")  # exact hit -> level-up + bonus
    check()
    clock.now += timedelta(days=4)
    svc.power_gift("campaign"); check()
    svc.add_system_donation(1.0, "motor", idempotency_key="sys"); check()
    svc.update_member_count(30); check()
    seq = next(e.seq for e in ps.read_events() if e.type == "DonationAdded")
    svc.delete_donation(seq); check()  # rebuild_from_events
    svc.delete_donation(seq); check()


def test_r1_8_legacy_decay_key_is_migrated_without_power_change(ps, clock):
    # Maintainer's live main.json: written by the pre-release build with power_decay_since
    data = _write_snapshot(ps, "main", level=7, power_acc=1500, evo_acc=900, goal_requirement=4180,
                           goal_started_at=_ago(clock, 10), power_decay_since=_ago(clock, 2),
                           last_user_count_sample=28)
    expected = 1500 - 2 * 100  # pre-release display: decay since power_decay_since

    state = ps.ProgressService("main").get_state()

    assert state.power_current == pytest.approx(expected / 100.0)
    persisted = _disk(ps, "main")
    assert "power_decay_since" not in persisted
    assert persisted["goal_started_at"] == data["power_decay_since"]
    assert persisted["power_acc"] == 1500 and persisted["evo_acc"] == 900 and persisted["level"] == 7
    HeadSnapshot.from_json(persisted)
    # A downgrade to v2.3.1 now shows the same power as well
    assert _head_displayed_power_cents(persisted, clock.now) == expected
    # Loading again changes nothing
    assert ps.ProgressService("main").get_state().power_current == pytest.approx(expected / 100.0)


def test_r1_8_v231_snapshot_keeps_displayed_power(ps, clock):
    data = _write_snapshot(ps, "main", power_acc=750, evo_acc=1200, goal_started_at=_ago(clock, 1.5))
    expected = _head_displayed_power_cents(data, clock.now)
    assert expected == 600

    state = ps.ProgressService("main").get_state()

    assert state.power_current == pytest.approx(expected / 100.0)
    persisted = _disk(ps, "main")
    assert persisted["goal_started_at"] == data["goal_started_at"]
    assert set(persisted) == set(data)


def test_r1_8_v231_naive_reset_timestamp_does_not_jump(ps, clock):
    # The old admin reset wrote a naive timestamp: v2.3.1 applied no decay at all
    _write_snapshot(ps, "main", power_acc=300, goal_started_at="2026-09-01T12:00:00.123456")

    assert ps.ProgressService("main").get_state().power_current == pytest.approx(3.0)
    persisted = _disk(ps, "main")
    assert datetime.fromisoformat(persisted["goal_started_at"]).tzinfo is not None
    clock.now += timedelta(days=1)
    assert ps.ProgressService("main").get_state().power_current == pytest.approx(2.0)


def test_r1_8_downgrade_after_donation_shows_same_power(ps, clock):
    # Hidden decay debt: $10 power, level goal started 20 days ago -> displayed $0
    _write_snapshot(ps, "main", power_acc=1000, goal_started_at=_ago(clock, 20))
    svc = ps.ProgressService("main")
    assert svc.get_state().power_current == 0.0

    state = svc.add_donation(10.0, idempotency_key="after-upgrade")

    assert state.power_current == pytest.approx(10.0)
    assert _head_displayed_power_cents(_disk(ps, "main"), clock.now) == 1000
    clock.now += timedelta(days=1)
    assert svc.get_state().power_current == pytest.approx(9.0)
    assert _head_displayed_power_cents(_disk(ps, "main"), clock.now) == 900


# ---------------------------------------------------------------------------
# R5-4 - rebuild_from_events == live path
# ---------------------------------------------------------------------------

def test_r5_4_exact_hit_bonus_not_counted_twice(ps, clock):
    svc = ps.ProgressService("main")
    live = svc.add_donation(3.0, idempotency_key="exact")  # level-1 goal is exactly $3
    assert live.level == 2
    assert live.power_current == pytest.approx(1.0)  # $0 excess + $1 exact-hit bonus
    assert live.total_donated == pytest.approx(3.0)

    rebuilt = svc.rebuild_from_events()

    # Before: bonus applied by the donation AND by the ExactHitBonusGranted event
    assert rebuilt.power_current == pytest.approx(live.power_current)
    assert rebuilt.total_donated == pytest.approx(live.total_donated)


def test_r5_4_system_donations_are_replayed(ps, clock):
    svc = ps.ProgressService("main")
    svc.add_donation(1.0, idempotency_key="d")
    clock.now += timedelta(days=3)
    live = svc.add_system_donation(1.0, "Monthly motor", idempotency_key="sys")
    assert live.power_current == pytest.approx(1.0)  # $1 decayed to 0, then +$1

    rebuilt = svc.rebuild_from_events()

    # Before: every system donation except the (no longer created) initial one was dropped
    assert rebuilt.power_current == pytest.approx(live.power_current)
    assert rebuilt.total_donated == pytest.approx(live.total_donated) == pytest.approx(2.0)


def test_r5_4_deleted_bonus_is_removed_and_restored(ps, clock):
    svc = ps.ProgressService("main")
    live = svc.add_donation(3.0, idempotency_key="exact")
    bonus_seq = next(e.seq for e in ps.read_events() if e.type == "ExactHitBonusGranted")

    deleted = svc.delete_donation(bonus_seq)
    assert deleted.power_current == pytest.approx(live.power_current - 1.0)
    assert deleted.level == live.level

    restored = svc.delete_donation(bonus_seq)
    assert restored.power_current == pytest.approx(live.power_current)


def test_r5_4_rebuild_keeps_goals_priced_by_the_live_path(ps, clock):
    svc = ps.ProgressService("main")
    svc.update_member_count(20)
    svc.add_donation(3.0, idempotency_key="lvl")  # level 2 priced for 20 members
    level2_goal = ps.load_snapshot("main").goal_requirement
    assert level2_goal == ps.requirement_for_level_and_bin(2, 1, member_count=20)
    clock.now += timedelta(hours=1)
    svc.update_member_count(45)  # community grew: must not re-price level 2
    svc.add_donation(0.5, idempotency_key="small")
    before = _fields(ps.load_snapshot("main"))

    seq = next(e.seq for e in ps.read_events() if e.payload.get("idempotency_key") == "small")
    svc.delete_donation(seq)
    svc.delete_donation(seq)  # restore

    assert _fields(ps.load_snapshot("main")) == before


def test_r5_4_rebuild_keeps_level_goal_repriced_at_startup(ps, clock):
    svc = ps.ProgressService("main")
    svc.add_donation(1.0, idempotency_key="a")
    snap = ps.load_snapshot("main")  # startup step re-priced the level-1 goal for 14 members
    snap.goal_requirement = ps.requirement_for_level_and_bin(1, 1, member_count=14)
    ps.persist_snapshot(snap)
    before = _fields(ps.load_snapshot("main"))

    svc.rebuild_from_events()

    assert _fields(ps.load_snapshot("main")) == before


def test_r5_4_reset_goal_survives_rebuild(ps, clock):
    reset_module = importlib.import_module("services.donation.unified.reset")
    ps.ProgressService("main").update_member_count(40)
    reset_module._write_fresh_snapshot(ps.runtime.paths)  # (event log would be cleared too)
    reset_goal = ps.load_snapshot("main").goal_requirement
    assert reset_goal == ps.requirement_for_level_and_bin(1, 1, member_count=40)

    svc = ps.ProgressService("main")
    svc.add_donation(1.0, idempotency_key="after-reset")
    svc.rebuild_from_events()

    assert ps.load_snapshot("main").goal_requirement == reset_goal


def _random_live_history(ps, clock, rng: random.Random, n_ops: int) -> None:
    svc = ps.ProgressService("main")
    counter = iter(range(10**6))

    def key() -> str:
        return f"k{next(counter)}"

    svc.add_donation(rng.randint(50, 400) / 100, donor="first", idempotency_key=key())
    for _ in range(n_ops):
        clock.now += timedelta(days=rng.choice([0, 0, 1, 3]),
                               seconds=rng.choice([0, 1, 59, 3600, 7 * 3600]) + rng.random())
        snap = ps.load_snapshot("main")
        op = rng.random()
        if op < 0.40:
            remaining = snap.goal_requirement - snap.evo_acc
            if snap.level < 11 and remaining > 0 and rng.random() < 0.35:
                cents = remaining  # exact hit
            else:
                cents = rng.randint(1, 900)
            svc.add_donation(cents / 100, donor=f"d{cents}", idempotency_key=key())
        elif op < 0.55:
            svc.add_system_donation(rng.randint(1, 500) / 100, "Monthly motor", idempotency_key=key())
        elif op < 0.65:
            svc.power_gift(f"campaign-{key()}")
        elif op < 0.85:
            svc.update_member_count(rng.randint(0, 60))
        else:
            svc.get_state()


@pytest.mark.parametrize("seed", range(25))
def test_r5_4_random_histories_rebuild_equals_live(ps, clock, tmp_path, seed):
    decay_file = tmp_path / "ddc_config" / "mech" / "decay.json"
    decay_file.parent.mkdir(parents=True, exist_ok=True)
    decay_file.write_text(json.dumps({"default": 100, "levels": {"1": 40, "2": 90, "3": 150, "4": 60}}),
                          encoding="utf-8")
    ps._decay_config_cache["data"] = None
    ps._decay_config_cache["last_load"] = 0
    rng = random.Random(seed)
    _random_live_history(ps, clock, rng, n_ops=30)
    svc = ps.ProgressService("main")
    live_snap = ps.load_snapshot("main")
    live = _fields(live_snap)

    svc.rebuild_from_events()
    assert _fields(ps.load_snapshot("main")) == live

    # Delete/restore round trip of a random donation-like event gives the live state back
    deletable = [e.seq for e in ps.read_events()
                 if e.type in ("DonationAdded", "PowerGiftGranted", "SystemDonationAdded", "ExactHitBonusGranted")]
    seq = rng.choice(deletable)
    svc.delete_donation(seq)
    svc.delete_donation(seq)
    rebuilt_snap = ps.load_snapshot("main")
    assert _fields(rebuilt_snap) == live

    # Same displayed state later on (decay keeps running identically)
    clock.now += timedelta(days=1, hours=7)
    assert ps.compute_ui_state(rebuilt_snap) == ps.compute_ui_state(live_snap)


# ---------------------------------------------------------------------------
# R1-7 - member count: newest source, startup step keeps concurrent updates
# ---------------------------------------------------------------------------

def _write_member_file(ps, count: int, last_updated=None) -> None:
    payload = {"count": count}
    if last_updated is not None:
        payload["last_updated"] = last_updated
    ps.MEMBER_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ps.MEMBER_COUNT_FILE.write_text(json.dumps(payload), encoding="utf-8")


def test_r1_7_member_count_for_goal_uses_newest_source(ps, clock):
    snap = ps.Snapshot(mech_id="main", last_user_count_sample=77)
    assert ps.member_count_for_goal(snap) == 77  # nothing else known
    assert ps.member_count_for_goal(ps.Snapshot(mech_id="main")) == 50  # historic default
    assert ps.member_count_for_goal(ps.Snapshot(mech_id="main"), default=0) == 0

    _write_member_file(ps, 14)  # no timestamp
    assert ps.member_count_for_goal(snap) == 14  # file beats the snapshot sample

    ps.ProgressService("main").update_member_count(40)
    assert ps.member_count_for_goal(snap) == 40  # event beats a file without timestamp

    _write_member_file(ps, 14, last_updated=_ago(clock, 1))
    assert ps.member_count_for_goal(snap) == 40  # event is newer

    clock.now += timedelta(minutes=5)
    _write_member_file(ps, 14, last_updated=clock.now.isoformat())
    assert ps.member_count_for_goal(snap) == 14  # file is newer

    # Rebuild view: samples after `at` do not exist yet
    before_both = clock.now - timedelta(hours=1)
    assert ps.member_count_for_goal(snap, at=before_both) == 77


def test_r1_7_level_up_ignores_stale_snapshot_sample(ps, clock):
    # Live data: latest event and member_count.json say 14, snapshot stuck at 28
    svc = ps.ProgressService("main")
    svc.update_member_count(14)
    _write_member_file(ps, 14, last_updated=clock.now.isoformat())
    snap = ps.load_snapshot("main")
    snap.last_user_count_sample = 28
    ps.persist_snapshot(snap)

    svc.add_donation(3.0, idempotency_key="lvl")

    after = ps.load_snapshot("main")
    assert after.level == 2
    assert after.goal_requirement == ps.requirement_for_level_and_bin(2, 1, member_count=14)
    assert after.last_user_count_sample == 14


def test_r1_7_startup_step_keeps_updates_made_while_it_runs(ps, clock, monkeypatch):
    from app.bot.startup_steps import member_count as step

    svc = ps.get_progress_service()
    _write_snapshot(ps, "main", level=2, power_acc=500, evo_acc=100, goal_started_at=clock.now.isoformat(),
                    goal_requirement=ps.requirement_for_level_and_bin(2, 1, member_count=28),
                    last_user_count_sample=28)

    def publish(count):
        svc.update_member_count(count)
        # A donation processed while the step runs must survive it as well
        ps.ProgressService("main").add_donation(0.25, idempotency_key="meanwhile")

    member_service = MagicMock()
    member_service.first_connected_guild.return_value = SimpleNamespace(name="g", id=1)
    member_service.compute_unique_member_count.return_value = 14
    member_service.publish_member_count.side_effect = publish
    member_service.persist_member_count_snapshot.side_effect = (
        lambda count, **_: _write_member_file(ps, count, last_updated=clock.now.isoformat()))
    monkeypatch.setattr(step, "get_member_count_service", lambda: member_service)
    logger = MagicMock()

    asyncio.run(step.initialize_member_count_step(SimpleNamespace(bot=object(), logger=logger)))

    logger.error.assert_not_called()
    after = ps.load_snapshot("main")
    assert after.last_user_count_sample == 14  # the stale copy wrote 28 back before
    assert after.goal_requirement == ps.requirement_for_level_and_bin(2, 1, member_count=14)
    assert after.evo_acc == 125 and after.cumulative_donations_cents == 2525  # donation kept
    assert after.last_event_seq == max(e.seq for e in ps.read_events() if e.type == "DonationAdded")


def test_r1_7_startup_step_does_not_set_a_goal_at_max_level(ps, clock):
    from app.bot.startup_steps import member_count as step

    _write_snapshot(ps, "main", level=11, goal_requirement=0, last_user_count_sample=30,
                    goal_started_at=clock.now.isoformat())
    asyncio.run(step._recalculate_goal("main", MagicMock()))
    assert ps.load_snapshot("main").goal_requirement == 0
