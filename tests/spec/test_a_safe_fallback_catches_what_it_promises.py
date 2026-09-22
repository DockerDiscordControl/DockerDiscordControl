# -*- coding: utf-8 -*-
"""The "safe fallbacks" in the status overview catch what they promise.

THE FINDING (review D16, pass 2, section 14 F6): three handlers in this file
carry a comment promising a blanket fallback and an except clause that names
a handful of types:

    except (RuntimeError) as e:
        # SAFE FALLBACK: Always allow updates on error to prevent stale data

    except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound):
        # Safe fallback: don't recreate on error

    except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound):
        # Safe fallback: allow updates

"Always" and "on error" are the promise; a named tuple is not. `make_update_decision`
calls `_get_channel_update_config`, which reads the channel configuration, and
`_should_recreate_message`, which reaches into the mech state - a KeyError, a
TypeError or an unreadable file from either of those walks straight past all
three clauses and out of the status loop.

This is the shape reviews C45, C46, C47 and C55 already removed elsewhere: a
narrow clause standing in front of a fallback written for something wider.
"""

from datetime import datetime, timezone

import pytest

from services.discord import status_overview_service as module
from services.discord.status_overview_service import StatusOverviewService

CHANNEL = 4242
CONFIG = {"channel_permissions": {str(CHANNEL): {"update_interval_minutes": 1}}}


@pytest.fixture
def service():
    return StatusOverviewService()


@pytest.mark.parametrize("failure", [KeyError("channel"), TypeError("bad shape"),
                                     OSError("config unreadable")])
def test_a_decision_still_comes_back(service, monkeypatch, failure):
    """THE FINDING: whatever the configuration lookup raises, the loop must
    get a decision rather than the exception."""
    def _explode(channel_id, global_config):
        raise failure

    monkeypatch.setattr(service, "_get_channel_update_config", _explode)

    decision = service.make_update_decision(CHANNEL, CONFIG)

    assert decision.should_update is True, (
        "the promise is to allow updates on error, so the overview cannot go stale"
    )


@pytest.mark.parametrize("failure", [KeyError("mech"), TypeError("bad shape")])
def test_the_recreate_question_answers_too(service, monkeypatch, failure):
    """The same for the recreate check, which reaches into the mech state."""
    def _explode(*args, **kwargs):
        raise failure

    monkeypatch.setattr(service, "_should_recreate_message", _explode)

    decision = service.make_update_decision(CHANNEL, CONFIG)

    assert decision.should_update is True


@pytest.mark.parametrize("failure", [KeyError("channel"), TypeError("bad shape")])
def test_the_module_level_helper_answers_too(monkeypatch, failure):
    """The third one, the function the status loop actually calls."""
    def _explode(*args, **kwargs):
        raise failure

    monkeypatch.setattr(module.StatusOverviewService, "make_update_decision", _explode)

    should_update, reason = module.should_update_channel_overview(CHANNEL, CONFIG)

    assert should_update is True
    assert "error" in reason


def test_a_runtime_error_is_still_handled(service, monkeypatch):
    """Counter-check: what the clauses already caught must keep working."""
    def _explode(channel_id, global_config):
        raise RuntimeError("as before")

    monkeypatch.setattr(service, "_get_channel_update_config", _explode)

    assert service.make_update_decision(CHANNEL, CONFIG).should_update is True


def test_an_ordinary_decision_is_unaffected(service):
    """Counter-check: the normal path must not start answering 'error'."""
    decision = service.make_update_decision(
        CHANNEL, CONFIG, last_update_time=datetime.now(timezone.utc))

    assert "error_fallback" not in decision.reason


def test_a_failed_recreate_check_does_not_force_an_update(service, monkeypatch):
    """The inner fallback has its own promise: "don't recreate on error" - not
    "update anyway". With the interval not yet reached, a failure of the
    recreate check must leave the decision at "no update needed"; letting it
    fall through to the outer fallback would force an update on every cycle
    (found by mutation M2 of review D16).
    """
    # The failure has to happen INSIDE _should_recreate_message, so its own
    # handler is the one that decides. Replacing the whole method would take
    # that handler away with it.
    def _explode():
        raise KeyError("mech")

    monkeypatch.setattr("services.mech.mech_state_manager.get_mech_state_manager",
                        _explode)
    monkeypatch.setattr(service, "_get_channel_update_config",
                        lambda channel_id, global_config: module.StatusOverviewUpdateConfig(
                            update_interval_minutes=60,
                            recreate_messages_on_inactivity=True,
                            inactivity_timeout_minutes=10))

    decision = service.make_update_decision(
        CHANNEL, CONFIG, last_update_time=datetime.now(timezone.utc))

    assert decision.should_update is False, (
        "the recreate check failed and the overview is now rewritten every cycle"
    )
    assert decision.should_recreate is False
