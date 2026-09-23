# -*- coding: utf-8 -*-
"""Changing the decay rate does not rewrite power that already decayed.

THE FINDING: every snapshot carries power_decay_per_day, written when a new
goal is set - and nothing ever read it. current_power_cents asked the config
for today's rate and applied it to the WHOLE span since the decay anchor,
which is days old. So an operator who edits decay.json does not change the
mech from now on: the power the panel shows jumps, because the past is
recomputed at the new rate. At 10x the rate a mech that had been charged for
a week reads zero.

The rate in the snapshot is the rate that span was measured at, and the new
rate takes over at the next power change, where settle_power_decay closes the
old span and starts a new one - the same place the anchor moves.

COUNTER-CHECK (2026-09-23): red before - the power dropped from 800 to 0
cents when the rate was raised, with no donation and no time passing.
test_the_new_rate_takes_over_after_a_settle holds the other side: simply
ignoring the config would be green without it.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from services.mech import progress_service as module


@pytest.fixture
def rate(monkeypatch):
    """Set the configured decay rate for all levels."""
    def set_rate(cents_per_day):
        monkeypatch.setattr(module, "get_decay_config_data",
                            lambda: {"default": cents_per_day})
    return set_rate


def _snapshot(days_ago, power_acc, decay_per_day):
    anchor = datetime.now(ZoneInfo("UTC")) - timedelta(days=days_ago)
    return module.Snapshot(
        mech_id="main", level=3, power_acc=power_acc,
        goal_started_at=anchor.isoformat(), power_decay_per_day=decay_per_day)


def test_a_raised_rate_leaves_the_past_alone(rate):
    snap = _snapshot(days_ago=2, power_acc=1000, decay_per_day=100)
    rate(100)
    assert module.current_power_cents(snap) == 800      # two days at 100

    rate(5000)                                          # the operator edits decay.json

    assert module.current_power_cents(snap) == 800, (
        "the power that had already decayed was recomputed at the new rate")


def test_the_new_rate_takes_over_after_a_settle(rate):
    """Counter-check: a changed rate must still take effect."""
    snap = _snapshot(days_ago=2, power_acc=1000, decay_per_day=100)
    rate(400)

    module.settle_power_decay(snap)                     # runs before every power change

    assert snap.power_acc == 800                        # the old span, at the old rate
    assert snap.power_decay_per_day == 400              # from here on, the new rate

    later = datetime.now(ZoneInfo("UTC")) + timedelta(days=1)
    assert module.current_power_cents(snap, later) == 400


def test_a_rate_of_zero_means_zero(rate):
    """A level that consumes nothing keeps its charge, whatever the config says.

    THE FINDING (independent review, 2026-09-23): the rate was read as
    `snap.power_decay_per_day or decay_per_day(level)`, which cannot tell "not
    filled in" from "this level really consumes nothing" - and the field has
    always defaulted to 100, so a 0 in a snapshot is deliberate. The final
    level has exactly that, and an operator may set it for any level.

    With the fallback, raising that level's rate in decay.json afterwards
    applied the new rate to the WHOLE span since the last power change - the
    very thing this file exists to prevent, left open for a zero.
    """
    snap = _snapshot(days_ago=30, power_acc=2000, decay_per_day=0)
    rate(200)

    assert module.current_power_cents(snap) == 2000, (
        "a level that consumes nothing lost its charge when the config changed")


def test_power_never_goes_below_zero(rate):
    """Counter-check: the clamp that was there before stays."""
    snap = _snapshot(days_ago=40, power_acc=1000, decay_per_day=100)
    rate(100)

    assert module.current_power_cents(snap) == 0
