# -*- coding: utf-8 -*-
"""Power at zero does not add up a debt the next donation has to pay off.

THE FINDING: the decay is the mech's energy consumption, and it is charged
against the span since the decay anchor. Every power change settles that span
first and moves the anchor - unless the event's timestamp cannot be read:
apply_power_event only settled `if at is not None` and otherwise left the
anchor where it was, weeks in the past. The donation was added to power_acc
and then eaten in the same breath by decay that had long since been shown as
zero. Measured: $5 onto a mech that had been at zero for three weeks left
600 cents in the file and showed 0.

An event without a readable time is settled at "now" instead, so the donation
stands and the consumption starts again from there.

COUNTER-CHECK (2026-09-23): red before - power_acc 600, shown 0. The
counter-checks keep the decay itself: an event WITH a time settles at that
time as before, and the consumption keeps running after the donation.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from services.mech import progress_service as module


def _mech_at_zero_for(days, power_acc=100, decay_per_day=100):
    """A level 1 mech (100 cents a day) whose power ran out `days` ago."""
    anchor = datetime.now(ZoneInfo("UTC")) - timedelta(days=days)
    return module.Snapshot(
        mech_id="main", level=1, power_acc=power_acc, evo_acc=0,
        goal_requirement=100000, power_decay_per_day=decay_per_day,
        goal_started_at=anchor.isoformat())


def _donation(units, ts):
    return module.Event(seq=1, ts=ts, type="DonationAdded", mech_id="main",
                        payload={"units": units})


def test_a_donation_after_a_long_zero_stands(monkeypatch):
    monkeypatch.setattr(module, "get_decay_config_data", lambda: {"default": 100})
    snap = _mech_at_zero_for(days=21)
    assert module.current_power_cents(snap) == 0        # three weeks of consumption

    module.apply_power_event(snap, _donation(500, "not a timestamp"))

    assert module.current_power_cents(snap) == 500, (
        "the donation was eaten by consumption that had already been shown as zero")
    assert snap.power_acc == 500, f"and the file says {snap.power_acc}"


def test_an_event_with_a_time_is_settled_at_that_time(monkeypatch):
    """Counter-check: the ordinary path is untouched."""
    monkeypatch.setattr(module, "get_decay_config_data", lambda: {"default": 100})
    snap = _mech_at_zero_for(days=21)
    at = datetime.now(ZoneInfo("UTC"))

    module.apply_power_event(snap, _donation(500, at.isoformat()))

    assert snap.power_acc == 500
    assert module._parse_utc(snap.goal_started_at) == at


def test_the_consumption_keeps_running_afterwards(monkeypatch):
    """Counter-check: settling must not switch the decay off."""
    monkeypatch.setattr(module, "get_decay_config_data", lambda: {"default": 100})
    snap = _mech_at_zero_for(days=21)

    module.apply_power_event(snap, _donation(500, "not a timestamp"))
    two_days_on = datetime.now(ZoneInfo("UTC")) + timedelta(days=2)

    assert module.current_power_cents(snap, two_days_on) == 300


def test_power_that_did_not_run_out_is_not_topped_up(monkeypatch):
    """Counter-check: settling is not a refill - what decayed stays gone."""
    monkeypatch.setattr(module, "get_decay_config_data", lambda: {"default": 100})
    snap = _mech_at_zero_for(days=1, power_acc=1000)   # 1000 - 100 = 900 left

    module.apply_power_event(snap, _donation(500, "not a timestamp"))

    assert module.current_power_cents(snap) == 1400
