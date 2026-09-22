# -*- coding: utf-8 -*-
"""The interval the operator set holds - a rate limit is not a reason to update.

THE FINDING: the update decision is `should_update_by_time or should_recreate
or force_recreate`, and should_recreate returned True as soon as the mech
state manager's should_force_recreate() said yes. That method is a RATE
LIMIT - "more than 30 seconds since the last recreate we marked" - and the
mark is only ever written when a mech level really changes. So in normal
operation it answers True for ever, should_recreate is True, and the overview
is updated every single minute however many minutes the operator configured.
The cog uses the same method correctly, as a rate limit BEHIND a reason
(a Glvl change or power depletion) and passes the result in as force_recreate.

The inactivity check below it - the thing
recreate_messages_on_inactivity is named after - could never be reached
either.

COUNTER-CHECK (2026-09-22): red before - with a 60-minute interval, a channel
active a second ago and an update a minute ago, the decision said "update".
"""

from datetime import datetime, timedelta, timezone

import pytest

from services.discord.status_overview_service import (StatusOverviewService,
                                                      StatusOverviewUpdateConfig)

NOW = datetime.now(timezone.utc)


@pytest.fixture
def service(monkeypatch):
    service = StatusOverviewService()

    class _AlwaysAllowed:
        def should_force_recreate(self, channel_id):
            return True          # the shipped rate limiter says this most of the time

        def mark_force_recreate(self, channel_id):
            pass

    monkeypatch.setattr("services.mech.mech_state_manager.get_mech_state_manager",
                        lambda: _AlwaysAllowed())
    return service


def _config(**overrides):
    fields = dict(update_interval_minutes=60, recreate_messages_on_inactivity=True,
                  inactivity_timeout_minutes=120, enable_auto_refresh=True)
    fields.update(overrides)
    return StatusOverviewUpdateConfig(**fields)


def _decide(service, config, last_update, last_activity, force=False, monkeypatch=None):
    """The decision as the loop makes it: the per-channel settings come from
    _get_channel_update_config, which reads the web-UI configuration."""
    service._get_channel_update_config = lambda channel_id, global_config: config
    return service.make_update_decision(channel_id=1, global_config={}, last_update_time=last_update,
                                        force_recreate=force, last_channel_activity=last_activity)


def test_an_interval_that_has_not_passed_means_no_update(service):
    decision = _decide(service, _config(), NOW - timedelta(seconds=61), NOW - timedelta(seconds=1))

    assert decision.should_update is False, decision.reason
    assert decision.should_recreate is False


def test_the_interval_still_lets_the_update_through_when_it_passed(service):
    """Counter-check: the interval must not become a blockade."""
    decision = _decide(service, _config(update_interval_minutes=1),
                       NOW - timedelta(seconds=61), NOW - timedelta(seconds=1))

    assert decision.should_update is True


def test_an_inactive_channel_is_still_recreated(service):
    """Counter-check: the inactivity rule this setting is named after keeps working."""
    decision = _decide(service, _config(), NOW - timedelta(seconds=61), NOW - timedelta(hours=3))

    assert decision.should_update is True and decision.should_recreate is True


def test_force_recreate_still_wins(service):
    """Counter-check: the cog's own reason (a Glvl change) still reaches through."""
    decision = _decide(service, _config(), NOW - timedelta(seconds=1), NOW, force=True)

    assert decision.should_update is True and decision.should_recreate is True
