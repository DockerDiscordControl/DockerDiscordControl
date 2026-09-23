# -*- coding: utf-8 -*-
"""The startup log says "gift granted" only when one was.

THE FINDING, caught on the running installation (2026-09-23): after a rebuild
the log read

    ✅ Power gift granted: $4.44 Power

and there was no gift. The event log held exactly two PowerGiftGranted events,
the last one three hours earlier over $4.50 - and $4.44 is what was left of it
after three hours of consumption. The step logged `state.power_level`, which
is the power the mech HAS, under a sentence that says something was given.

I believed the line myself while reading it, which is the whole problem: every
restart of an installation whose mech has power reports a gift that did not
happen. SPEC.md Z3.

COUNTER-CHECK (2026-09-23): red before - a mech with power and no gift still
produced "Power gift granted". The second test keeps the real case, where the
line must still appear.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.bot.startup_steps import power as step_module


def _run(monkeypatch, *, gift_dollars, power_level, version="3.0.0",
         welcome_dollars=None):
    """Run the step against an adapter that grants `gift_dollars` (or nothing).

    ``welcome_dollars`` is what the FIRST call (the welcome gift) hands out -
    the case the step used to lose, because the release call overwrote the
    state it read the amount from.
    """
    class Adapter:
        def power_gift(self, campaign_id, gift_cents=None):
            return SimpleNamespace(power_level=power_level, level=1, gift=welcome_dollars)

        def release_gift(self, version):
            return SimpleNamespace(power_level=power_level, level=1, gift=gift_dollars)

    monkeypatch.setattr("services.mech.mech_service_adapter.get_mech_service", lambda: Adapter())
    monkeypatch.setenv("DDC_VERSION", version)
    context = SimpleNamespace(logger=MagicMock())
    asyncio.run(step_module.grant_power_gift_step(context))
    return [str(call) for call in context.logger.info.call_args_list]


def test_no_gift_no_claim(monkeypatch):
    lines = _run(monkeypatch, gift_dollars=None, power_level=4.44)

    # "gift granted:", not "granted": the honest line for this case says
    # "not needed (power > 0 or already granted)" and must stay allowed.
    assert not any("gift granted:" in line for line in lines), (
        f"the log claims a gift that did not happen: {lines}")
    assert any("not needed" in line for line in lines), lines


def test_a_real_gift_is_still_reported(monkeypatch):
    """Counter-check: the operator must still see it when it happens."""
    lines = _run(monkeypatch, gift_dollars=4.5, power_level=4.5)

    assert any("gift granted:" in line for line in lines), lines
    assert any("4.5" in line or "4.50" in line for line in lines), lines


def test_the_welcome_gift_is_reported_too(monkeypatch):
    """A fresh install gets its welcome gift, and then the release gift is refused.

    THE FINDING (independent review, 2026-09-23): the step overwrote `state`
    with the release call, so only the LAST call's gift was reported. On the
    one boot where a gift really happened - power $0, welcome gift $2.00, then
    the release gift refused because power is no longer 0 - the operator read
    "Power gift not needed". That is the very failure this file was written
    against, on the path it did not cover.
    """
    lines = _run(monkeypatch, welcome_dollars=2.0, gift_dollars=None, power_level=2.0)

    assert any("gift granted:" in line for line in lines), lines
    assert any("2.0" in line or "2.00" in line for line in lines), lines
