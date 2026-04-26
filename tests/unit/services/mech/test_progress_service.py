# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Progress Service Unit Tests                    #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Functional unit-tests for services.mech.progress_service.

These tests focus on the lower-level helpers (decay, requirements, snapshot
IO, replay) and edge-cases of the ProgressService class that are not
exercised by the existing donation/runtime suites.

NO sys.modules manipulation — only env vars and importlib.reload.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.mech.progress import reset_progress_runtime
from services.mech.progress_paths import clear_progress_paths_cache


def _make_config(timezone_name: str = "UTC") -> dict:
    """Standard small-difficulty test config so level-ups are quick."""
    return {
        "timezone": timezone_name,
        "difficulty_bins": [0, 50],
        "level_base_costs": {str(level): 100 for level in range(1, 12)},
        "bin_to_dynamic_cost": {str(b): 0 for b in range(1, 22)},
        "mech_power_decay_per_day": {"default": 100},
    }


@pytest.fixture
def progress_env(tmp_path, monkeypatch):
    """Isolated progress runtime + reloaded module + stubbed evolution mode."""
    data_dir = tmp_path / "progress"
    config_dir = tmp_path / "ddc_config"
    monkeypatch.setenv("DDC_PROGRESS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DDC_CONFIG_DIR", str(config_dir))

    reset_progress_runtime()
    clear_progress_paths_cache()

    progress_service = importlib.reload(
        importlib.import_module("services.mech.progress_service")
    )
    progress_service._progress_service = None

    runtime = progress_service.runtime
    config = _make_config()
    runtime.configure_defaults(config)
    runtime.paths.config_file.write_text(json.dumps(config), encoding="utf-8")
    progress_service.CFG = runtime.load_config(refresh=True)
    progress_service.TZ = runtime.timezone(refresh=True)

    # Stub config_service.get_config_service so requirement_for_level_and_bin
    # uses dynamic mode (no multiplier).
    config_module = importlib.import_module("services.config.config_service")
    monkeypatch.setattr(
        config_module,
        "get_config_service",
        lambda: SimpleNamespace(
            get_evolution_mode_service=lambda request: config_module.GetEvolutionModeResult(
                success=True,
                use_dynamic=True,
                difficulty_multiplier=1.0,
            )
        ),
        raising=False,
    )

    # Reset the decay-config cache so each test starts fresh.
    progress_service._decay_config_cache["data"] = None
    progress_service._decay_config_cache["last_load"] = 0

    yield progress_service

    progress_service._progress_service = None
    reset_progress_runtime()
    clear_progress_paths_cache()


# ---------------------------------------------------------------------------
# Decay config & decay_per_day
# ---------------------------------------------------------------------------

def test_get_decay_config_data_returns_default_when_file_missing(progress_env, tmp_path):
    """No decay.json under DDC_CONFIG_DIR -> returns {"default": 100}."""
    data = progress_env.get_decay_config_data()
    assert data == {"default": 100}


def test_get_decay_config_data_loads_from_ddc_config_dir(progress_env, monkeypatch, tmp_path):
    """Honours DDC_CONFIG_DIR override (Bug-4 fix path)."""
    config_dir = tmp_path / "ddc_config"
    mech_dir = config_dir / "mech"
    mech_dir.mkdir(parents=True, exist_ok=True)
    decay_payload = {"default": 200, "levels": {"1": 50, "5": 500, "10": 1500}}
    (mech_dir / "decay.json").write_text(json.dumps(decay_payload), encoding="utf-8")

    # Bust cache so the freshly-written file is read.
    progress_env._decay_config_cache["data"] = None
    progress_env._decay_config_cache["last_load"] = 0

    data = progress_env.get_decay_config_data()
    assert data == decay_payload


def test_get_decay_config_data_caches_within_ttl(progress_env, monkeypatch, tmp_path):
    """Subsequent calls within 10s TTL return cached data without re-reading file."""
    config_dir = tmp_path / "ddc_config"
    mech_dir = config_dir / "mech"
    mech_dir.mkdir(parents=True, exist_ok=True)
    (mech_dir / "decay.json").write_text(json.dumps({"default": 77}), encoding="utf-8")

    progress_env._decay_config_cache["data"] = None
    progress_env._decay_config_cache["last_load"] = 0

    first = progress_env.get_decay_config_data()
    # Now overwrite the file — cache should still serve the original
    (mech_dir / "decay.json").write_text(json.dumps({"default": 999}), encoding="utf-8")
    second = progress_env.get_decay_config_data()
    assert first == second == {"default": 77}


def test_get_decay_config_data_handles_invalid_json(progress_env, tmp_path):
    """Malformed decay.json -> returns default on exception."""
    config_dir = tmp_path / "ddc_config"
    mech_dir = config_dir / "mech"
    mech_dir.mkdir(parents=True, exist_ok=True)
    (mech_dir / "decay.json").write_text("not-json{{{", encoding="utf-8")

    progress_env._decay_config_cache["data"] = None
    progress_env._decay_config_cache["last_load"] = 0

    data = progress_env.get_decay_config_data()
    assert data == {"default": 100}


def test_decay_per_day_uses_level_specific_value(progress_env, tmp_path):
    """Level-keyed decay overrides the default."""
    config_dir = tmp_path / "ddc_config"
    mech_dir = config_dir / "mech"
    mech_dir.mkdir(parents=True, exist_ok=True)
    (mech_dir / "decay.json").write_text(
        json.dumps({"default": 100, "levels": {"3": 250, "7": 700}}),
        encoding="utf-8",
    )

    progress_env._decay_config_cache["data"] = None
    progress_env._decay_config_cache["last_load"] = 0

    assert progress_env.decay_per_day(3) == 250
    assert progress_env.decay_per_day(7) == 700
    # Unknown level -> default
    assert progress_env.decay_per_day(2) == 100


def test_decay_per_day_returns_default_when_no_levels(progress_env):
    """No level mapping -> default value used for any level."""
    for level in (1, 5, 11):
        assert progress_env.decay_per_day(level) == 100


# ---------------------------------------------------------------------------
# requirement_for_level_and_bin / current_bin / bin_to_tier_name
# ---------------------------------------------------------------------------

def test_requirement_invalid_level_falls_back_to_level_1(progress_env):
    # level=0 invalid → uses level 1, base_cost=100, no member_count → bin dynamic=0
    val = progress_env.requirement_for_level_and_bin(0, 1, member_count=None)
    assert val == 100


def test_requirement_invalid_bin_falls_back_to_bin_1(progress_env):
    val = progress_env.requirement_for_level_and_bin(1, 99, member_count=None)
    assert val == 100  # base 100 + bin1 dynamic 0


def test_requirement_negative_member_count_normalised(progress_env):
    # -5 normalised to 0 → 0 members ≤ FREEBIE_MEMBERS (10) → dynamic 0
    val = progress_env.requirement_for_level_and_bin(1, 1, member_count=-5)
    assert val == 100  # base only


def test_requirement_member_count_above_discord_cap(progress_env):
    """member_count > 100k is capped at 100k (still computed precisely)."""
    val = progress_env.requirement_for_level_and_bin(1, 1, member_count=150000)
    # capped to 100000 → billable = 99990 → dynamic = 999900 cents = $9999
    # base 100 + 999900 = 1_000_000 (capped at $10,000)
    assert val == 1_000_000


def test_requirement_member_count_string_coerced(progress_env):
    """String numeric member_count is coerced to int."""
    val = progress_env.requirement_for_level_and_bin(1, 1, member_count="20")
    # billable = 20-10 = 10, dynamic = 100 cents, base 100 → 200
    assert val == 200


def test_requirement_member_count_invalid_type_uses_none(progress_env):
    """Non-coercible type → falls back to bin-based dynamic cost."""
    val = progress_env.requirement_for_level_and_bin(1, 1, member_count=object())
    # member_count becomes None → uses bin_to_dynamic_cost[1]=0 → 100
    assert val == 100


def test_current_bin_from_user_count(progress_env):
    # bins = [0, 50] in the test config
    assert progress_env.current_bin(0) == 1
    assert progress_env.current_bin(49) == 1
    assert progress_env.current_bin(50) == 2
    assert progress_env.current_bin(10000) == 2


def test_bin_to_tier_name_all_branches(progress_env):
    assert progress_env.bin_to_tier_name(1) == "Tiny Community"
    assert progress_env.bin_to_tier_name(2) == "Small Community"
    assert progress_env.bin_to_tier_name(3) == "Medium Community"
    assert progress_env.bin_to_tier_name(4) == "Large Community"
    assert progress_env.bin_to_tier_name(7) == "Huge Community"
    assert progress_env.bin_to_tier_name(15) == "Massive Community"


# ---------------------------------------------------------------------------
# Snapshot persistence / load corruption recovery
# ---------------------------------------------------------------------------

def test_load_snapshot_creates_when_missing(progress_env):
    snap = progress_env.load_snapshot("freshmech")
    assert snap.mech_id == "freshmech"
    assert snap.level == 1
    assert progress_env.snapshot_path("freshmech").exists()


def test_load_snapshot_recovers_from_corrupt_file(progress_env):
    p = progress_env.snapshot_path("corrupt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not-json", encoding="utf-8")

    snap = progress_env.load_snapshot("corrupt")
    assert snap.mech_id == "corrupt"
    assert snap.level == 1


def test_persist_snapshot_atomic_write(progress_env):
    snap = progress_env.Snapshot(mech_id="atomic")
    snap.level = 5
    snap.power_acc = 1234
    progress_env.persist_snapshot(snap)

    p = progress_env.snapshot_path("atomic")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["level"] == 5
    assert data["power_acc"] == 1234
    assert data["mech_id"] == "atomic"


def test_snapshot_path_sanitises_mech_id(progress_env):
    p = progress_env.snapshot_path("../../etc/passwd")
    # ".." replaced with "_", "/" replaced with "_"
    assert "etc" in p.name
    assert ".." not in p.name


# ---------------------------------------------------------------------------
# Event log / sequence
# ---------------------------------------------------------------------------

def test_read_events_empty_when_no_log(progress_env):
    # Empty events.jsonl present after fixture ensure_layout
    assert progress_env.read_events() == []


def test_append_and_read_events_roundtrip(progress_env):
    e1 = progress_env.Event(seq=1, ts="2025-01-01T00:00:00+00:00", type="X", mech_id="m", payload={"a": 1})
    e2 = progress_env.Event(seq=2, ts="2025-01-02T00:00:00+00:00", type="Y", mech_id="m", payload={"b": 2})
    progress_env.append_event(e1)
    progress_env.append_event(e2)

    evts = progress_env.read_events()
    assert len(evts) == 2
    assert evts[0].seq == 1 and evts[0].type == "X"
    assert evts[1].seq == 2 and evts[1].payload == {"b": 2}


def test_next_seq_increments(progress_env):
    a = progress_env.next_seq()
    b = progress_env.next_seq()
    c = progress_env.next_seq()
    assert b == a + 1
    assert c == b + 1


# ---------------------------------------------------------------------------
# Donation core – edge-cases
# ---------------------------------------------------------------------------

def test_add_donation_negative_amount_raises(progress_env):
    svc = progress_env.ProgressService("neg")
    with pytest.raises(ValueError):
        svc.add_donation(-1.0)


def test_add_donation_zero_amount_raises(progress_env):
    svc = progress_env.ProgressService("zero")
    with pytest.raises(ValueError):
        svc.add_donation(0.0)


def test_add_donation_idempotency_key(progress_env):
    svc = progress_env.ProgressService("idem")
    state1 = svc.add_donation(0.5, donor="alice", idempotency_key="same-key")
    state2 = svc.add_donation(0.5, donor="alice", idempotency_key="same-key")
    # Second call returns existing state without recording new event
    donations = [e for e in progress_env.read_events()
                 if e.mech_id == "idem" and e.type == "DonationAdded"]
    assert len(donations) == 1
    assert state1.total_donated == state2.total_donated


def test_add_donation_triggers_level_up(progress_env):
    """A donation matching the requirement triggers a LevelUp event."""
    svc = progress_env.ProgressService("levelup")
    # Requirement for level 1 in our config = $1.00 (100 cents)
    state = svc.add_donation(1.00, donor="bob")
    assert state.level == 2
    # Level-up events written
    types = {e.type for e in progress_env.read_events() if e.mech_id == "levelup"}
    assert "LevelUpCommitted" in types
    assert "ExactHitBonusGranted" in types  # exact hit


def test_add_donation_huge_amount_caps_at_level_11(progress_env):
    """A massive donation cannot push level beyond 11."""
    svc = progress_env.ProgressService("huge")
    state = svc.add_donation(100000.0, donor="whale")
    assert state.level == 11


def test_apply_donation_units_at_level_11(progress_env):
    """At max level, donation only adds power, no level-up events."""
    snap = progress_env.Snapshot(mech_id="mx", level=11, goal_requirement=0)
    new_snap, lvl_events, bonus = progress_env.apply_donation_units(snap, 5000)
    assert new_snap.level == 11
    assert new_snap.power_acc == 5000
    assert lvl_events == []
    assert bonus is None


# ---------------------------------------------------------------------------
# system_donation edge-cases
# ---------------------------------------------------------------------------

def test_add_system_donation_non_numeric_raises(progress_env):
    svc = progress_env.ProgressService("sys1")
    with pytest.raises(TypeError):
        svc.add_system_donation("not-a-number", "Event")


def test_add_system_donation_negative_raises(progress_env):
    svc = progress_env.ProgressService("sys2")
    with pytest.raises(ValueError):
        svc.add_system_donation(-5.0, "Event")


def test_add_system_donation_too_large_raises(progress_env):
    svc = progress_env.ProgressService("sys3")
    with pytest.raises(ValueError):
        svc.add_system_donation(5000.0, "Event")  # > $1000 max


def test_add_system_donation_empty_event_name_raises(progress_env):
    svc = progress_env.ProgressService("sys4")
    with pytest.raises(ValueError):
        svc.add_system_donation(1.0, "")


def test_add_system_donation_truncates_long_event_name(progress_env):
    svc = progress_env.ProgressService("sys5")
    long_name = "a" * 250
    state = svc.add_system_donation(1.0, long_name)
    assert state.power_current >= 1.0
    # Find event and verify truncation
    evts = [e for e in progress_env.read_events()
            if e.mech_id == "sys5" and e.type == "SystemDonationAdded"]
    assert len(evts) == 1
    assert len(evts[0].payload["event_name"]) == 100


def test_add_system_donation_truncates_long_description(progress_env):
    svc = progress_env.ProgressService("sys6")
    long_desc = "x" * 1000
    svc.add_system_donation(1.0, "Event", description=long_desc)
    evts = [e for e in progress_env.read_events()
            if e.mech_id == "sys6" and e.type == "SystemDonationAdded"]
    assert len(evts[0].payload["description"]) == 500


def test_add_system_donation_idempotency(progress_env):
    svc = progress_env.ProgressService("sys7")
    svc.add_system_donation(2.0, "Birthday", idempotency_key="bday-2025")
    svc.add_system_donation(2.0, "Birthday", idempotency_key="bday-2025")
    evts = [e for e in progress_env.read_events()
            if e.mech_id == "sys7" and e.type == "SystemDonationAdded"]
    assert len(evts) == 1


def test_add_system_donation_only_power_not_evolution(progress_env):
    svc = progress_env.ProgressService("sys8")
    # Sub-level-up amount: 50 cents
    state = svc.add_system_donation(0.50, "Mini-Event")
    assert state.power_current == 0.50
    # Evolution unchanged
    assert state.evo_current == 0.0


def test_add_system_donation_amount_rounds_to_zero_no_op(progress_env):
    """Very tiny amount rounds to 0 cents — should be a no-op without raising."""
    svc = progress_env.ProgressService("sys9")
    state = svc.add_system_donation(0.001, "Tiny")
    # Should not raise; power unchanged
    assert state.power_current == 0.0


# ---------------------------------------------------------------------------
# delete_donation
# ---------------------------------------------------------------------------

def test_delete_donation_unknown_seq_raises(progress_env):
    svc = progress_env.ProgressService("del1")
    with pytest.raises(ValueError, match="not found"):
        svc.delete_donation(99999)


def test_delete_donation_then_restore_via_toggle(progress_env):
    """Deleting twice restores the donation (toggle pattern)."""
    svc = progress_env.ProgressService("del2")
    svc.add_donation(0.30, donor="x", idempotency_key="d1")
    # find the seq
    add_evt = next(e for e in progress_env.read_events()
                   if e.mech_id == "del2" and e.type == "DonationAdded")
    # First delete: removes it
    state1 = svc.delete_donation(add_evt.seq)
    assert state1.total_donated == 0.0
    # Second delete: restores it
    state2 = svc.delete_donation(add_evt.seq)
    assert state2.total_donated == pytest.approx(0.30)


def test_delete_donation_supports_power_gift(progress_env):
    svc = progress_env.ProgressService("del3")
    state, gift = svc.power_gift("campaign-1")
    assert gift is not None
    gift_evt = next(e for e in progress_env.read_events()
                    if e.mech_id == "del3" and e.type == "PowerGiftGranted")
    new_state = svc.delete_donation(gift_evt.seq)
    # After deletion: power should be 0 (gift removed)
    assert new_state.power_current == 0.0


# ---------------------------------------------------------------------------
# rebuild_from_events / state recompute
# ---------------------------------------------------------------------------

def test_rebuild_from_events_with_no_events(progress_env):
    svc = progress_env.ProgressService("empty")
    state = svc.rebuild_from_events()
    assert state.level == 1
    assert state.total_donated == 0.0


def test_rebuild_from_events_replays_donations(progress_env):
    svc = progress_env.ProgressService("replay")
    svc.add_donation(0.50, donor="a", idempotency_key="r1")
    svc.add_donation(0.30, donor="b", idempotency_key="r2")

    # Now wipe snapshot so rebuild has to recompute
    progress_env.snapshot_path("replay").unlink(missing_ok=True)

    state = svc.rebuild_from_events()
    assert state.total_donated == pytest.approx(0.80)


def test_rebuild_from_events_handles_member_count_event(progress_env):
    svc = progress_env.ProgressService("mc-rebuild")
    svc.update_member_count(42)
    progress_env.snapshot_path("mc-rebuild").unlink(missing_ok=True)
    state = svc.rebuild_from_events()
    assert state.member_count == 42


def test_rebuild_from_events_handles_initial_system_donation(progress_env):
    """is_initial=True system donations are replayed (others ignored)."""
    svc = progress_env.ProgressService("sysreplay")
    # Manually craft an initial system donation event
    evt = progress_env.Event(
        seq=progress_env.next_seq(),
        ts=progress_env.now_utc_iso(),
        type="SystemDonationAdded",
        mech_id="sysreplay",
        payload={"is_initial": True, "power_units": 300, "event_name": "init"},
    )
    progress_env.append_event(evt)
    # And a non-initial one (should be ignored on replay)
    evt2 = progress_env.Event(
        seq=progress_env.next_seq(),
        ts=progress_env.now_utc_iso(),
        type="SystemDonationAdded",
        mech_id="sysreplay",
        payload={"is_initial": False, "power_units": 999, "event_name": "later"},
    )
    progress_env.append_event(evt2)

    progress_env.snapshot_path("sysreplay").unlink(missing_ok=True)
    state = svc.rebuild_from_events()
    # Only the initial $3 was applied to power
    assert state.power_current == pytest.approx(3.0, abs=0.5)


# ---------------------------------------------------------------------------
# update_member_count / tick_decay / power_gift
# ---------------------------------------------------------------------------

def test_update_member_count_persists_and_logs_event(progress_env):
    svc = progress_env.ProgressService("mc")
    svc.update_member_count(100)
    snap = progress_env.load_snapshot("mc")
    assert snap.last_user_count_sample == 100
    evts = [e for e in progress_env.read_events()
            if e.mech_id == "mc" and e.type == "MemberCountUpdated"]
    assert len(evts) == 1
    assert evts[0].payload["member_count"] == 100


def test_update_member_count_clamps_negative_to_zero(progress_env):
    svc = progress_env.ProgressService("mc-neg")
    svc.update_member_count(-15)
    snap = progress_env.load_snapshot("mc-neg")
    assert snap.last_user_count_sample == 0


def test_tick_decay_returns_state(progress_env):
    svc = progress_env.ProgressService("tick")
    state = svc.tick_decay()
    assert state.level == 1


def test_power_gift_skipped_when_power_already_positive(progress_env):
    svc = progress_env.ProgressService("gift1")
    # Donate first to ensure power > 0
    svc.add_donation(0.30, idempotency_key="seed")
    state, gift = svc.power_gift("c1")
    assert gift is None
    assert state.power_current > 0


def test_power_gift_idempotent_per_campaign(progress_env):
    svc = progress_env.ProgressService("gift2")
    state1, gift1 = svc.power_gift("camp-A")
    assert gift1 is not None
    # Second call with same campaign — should be skipped (gift None)
    # but only if power is still 0 — the first one bumped power, so we have to
    # zero out first via direct snapshot manipulation
    snap = progress_env.load_snapshot("gift2")
    snap.power_acc = 0
    progress_env.persist_snapshot(snap)
    state2, gift2 = svc.power_gift("camp-A")
    assert gift2 is None  # campaign already used


def test_deterministic_gift_1_3_in_range(progress_env):
    """The deterministic gift always falls in [100, 300] cents."""
    for camp in ("a", "b", "c", "x", "y", "z", "1", "2"):
        cents = progress_env.deterministic_gift_1_3("mech1", camp)
        assert cents in (100, 200, 300)


# ---------------------------------------------------------------------------
# get_progress_service singleton
# ---------------------------------------------------------------------------

def test_get_progress_service_singleton(progress_env):
    a = progress_env.get_progress_service("foo")
    b = progress_env.get_progress_service("bar")
    # Singleton: second call returns the FIRST instance, ignoring new mech_id
    assert a is b


# ---------------------------------------------------------------------------
# UI state computation edge-cases
# ---------------------------------------------------------------------------

def test_compute_ui_state_at_level_11(progress_env):
    snap = progress_env.Snapshot(
        mech_id="ui11",
        level=11,
        evo_acc=0,
        power_acc=500,
        goal_requirement=0,
        cumulative_donations_cents=10000,
    )
    state = progress_env.compute_ui_state(snap)
    assert state.level == 11
    assert state.power_percent <= 100
    assert state.evo_percent == 100  # max-level branch
    assert not state.can_level_up


def test_compute_ui_state_offline_when_power_zero(progress_env):
    snap = progress_env.Snapshot(mech_id="off", level=2, power_acc=0, goal_requirement=200)
    state = progress_env.compute_ui_state(snap)
    assert state.is_offline is True


def test_compute_ui_state_continuous_decay(progress_env):
    """An old goal_started_at causes power decay in the UI state."""
    # Set goal_started_at to 2 days ago, decay 100 cents/day → 200 cents decay
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    snap = progress_env.Snapshot(
        mech_id="decay-ui",
        level=1,
        power_acc=500,
        goal_requirement=1000,
        goal_started_at=past,
    )
    state = progress_env.compute_ui_state(snap)
    # Power should be decreased by ~$2 → ~$3 left
    assert state.power_current < 5.0
    assert state.power_current >= 2.5


def test_compute_ui_state_invalid_goal_started_at_handled(progress_env):
    """Bad goal_started_at string gracefully falls back without raising."""
    snap = progress_env.Snapshot(
        mech_id="bad-ts",
        level=1,
        power_acc=500,
        goal_requirement=1000,
        goal_started_at="not-a-timestamp",
    )
    state = progress_env.compute_ui_state(snap)
    # No decay applied, original power retained
    assert state.power_current == 5.0


# ---------------------------------------------------------------------------
# now_utc_iso / today_local_str
# ---------------------------------------------------------------------------

def test_now_utc_iso_format(progress_env):
    iso = progress_env.now_utc_iso()
    # parseable as datetime
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    assert dt.tzinfo is not None


def test_today_local_str_format(progress_env):
    s = progress_env.today_local_str()
    # YYYY-MM-DD
    assert len(s) == 10
    assert s[4] == "-" and s[7] == "-"


# ---------------------------------------------------------------------------
# Snapshot dataclass roundtrip
# ---------------------------------------------------------------------------

def test_snapshot_to_from_json_roundtrip(progress_env):
    snap = progress_env.Snapshot(
        mech_id="rt",
        level=3,
        evo_acc=150,
        power_acc=200,
        goal_requirement=400,
        difficulty_bin=2,
        cumulative_donations_cents=1500,
    )
    payload = snap.to_json()
    restored = progress_env.Snapshot.from_json(payload)
    assert restored == snap


def test_event_to_json_roundtrip(progress_env):
    evt = progress_env.Event(
        seq=42,
        ts="2025-04-01T10:00:00+00:00",
        type="DonationAdded",
        mech_id="rt-evt",
        payload={"units": 500, "donor": "x"},
    )
    j = evt.to_json()
    assert j["seq"] == 42
    assert j["type"] == "DonationAdded"
    assert j["payload"] == {"units": 500, "donor": "x"}


# ---------------------------------------------------------------------------
# set_new_goal_for_next_level
# ---------------------------------------------------------------------------

def test_set_new_goal_for_next_level_updates_snapshot(progress_env):
    snap = progress_env.Snapshot(mech_id="goal", level=1)
    progress_env.set_new_goal_for_next_level(snap, user_count=20)
    assert snap.goal_requirement > 0
    assert snap.last_user_count_sample == 20
    assert snap.goal_started_at != ""
