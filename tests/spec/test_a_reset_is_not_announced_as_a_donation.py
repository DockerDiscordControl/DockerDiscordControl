# -*- coding: utf-8 -*-
"""A reset of the ledger is not a completed donation.

THE FINDING (review D35, pass 2, section 17 F3): `emit_reset_event` - what
runs when an admin resets the donation ledger - emitted

    event_type="donation_completed"

with a payload of `{action: 'reset', source, old_power, new_power, ...}`.
No amount, no donor. `emit_donation_event`, for an actual donation, emits the
same event type with amount and username instead.

NOT a defect in the running installation, and that matters for how this is
judged: both listeners registered for `donation_completed` today are cache
invalidators, both read the amount with `.get('amount', 'unknown')`, and
both do exactly the right thing after a reset - power and level really did
change, so the caches really must go.

What IS wrong today is one line in each of them:

    reason = f"Donation completed: ${event_info.get('amount', 'unknown')}"

After an admin resets the ledger, the log of a product whose entire subject
is money says a donation completed, for an unknown amount. Nobody donated.

And what it sets up is the trap: the next listener registered for
`donation_completed` - a donation announcement is the obvious one - would
announce a reset as a donation to a Discord channel. That is the same shape
as the routes that answer a failure and a deliberate empty result with one
status (D23), and it costs one word to close.

Resets now have their own event type. The two cache services listen for both,
because both events mean the same thing to a cache: the numbers moved.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.donation.unified.events import emit_reset_event

STATE_BEFORE = SimpleNamespace(Power=42.0, level=3)
STATE_AFTER = SimpleNamespace(Power=0.0, level=1)


class _Recorder:
    """An event manager that only writes down what it was told."""

    def __init__(self):
        self.emitted = []
        self.registered = []

    def emit_event(self, *, event_type, source_service, data):
        self.emitted.append((event_type, data))

    def register_listener(self, event_type, callback):
        self.registered.append(event_type)


def _reset():
    recorder = _Recorder()
    emit_reset_event(recorder, source="admin panel",
                     old_state=STATE_BEFORE, new_state=STATE_AFTER)
    return recorder


def test_a_reset_does_not_claim_a_donation_completed():
    recorder = _reset()

    event_type, data = recorder.emitted[0]
    assert event_type != "donation_completed", (
        f"a reset was emitted as {event_type!r} with {sorted(data)} - any "
        f"listener that believes the event type would treat it as a donation"
    )


def test_a_reset_still_says_it_is_a_reset_in_the_payload():
    """A pin: the action field is what the listeners branch on."""
    _, data = _reset().emitted[0]

    assert data["action"] == "reset"
    assert data["source"] == "admin panel"
    assert data["old_power"] == 42.0 and data["new_power"] == 0.0


@pytest.mark.parametrize("module_name,factory", [
    ("services.mech.mech_status_cache_service", "MechStatusCacheService"),
    ("services.mech.animation_cache_service", "AnimationCacheService"),
])
def test_the_caches_still_hear_about_a_reset(module_name, factory, monkeypatch):
    """The promise the new event type must not break.

    A reset moves power and level, so the caches must go - that is what they
    were getting out of `donation_completed` all along. They now listen for
    both, and this is the test that noticed if they did not.
    """
    import importlib

    module = importlib.import_module(module_name)
    recorder = _Recorder()
    monkeypatch.setattr("services.infrastructure.event_manager.get_event_manager",
                        lambda: recorder)

    service = getattr(module, factory).__new__(getattr(module, factory))
    service.logger = MagicMock()
    service._handle_donation_event = lambda event_data: None
    service._handle_state_change_event = lambda event_data: None
    service._setup_event_listeners()

    reset_type = _reset().emitted[0][0]
    assert reset_type in recorder.registered, (
        f"{factory} listens for {recorder.registered} and a reset is emitted "
        f"as {reset_type!r} - the caches would keep showing the old power"
    )
    assert "donation_completed" in recorder.registered, (
        "a real donation no longer reaches this cache"
    )


RESET_PAYLOAD = {"action": "reset", "source": "admin panel", "old_power": 42.0,
                 "new_power": 0.0, "old_level": 3, "new_level": 1,
                 "level_changed": True}
DONATION_PAYLOAD = {"amount": 25.0, "username": "somebody"}


def _handle(module_name, factory, payload, monkeypatch):
    """Put one event through the real handler and give back what it logged."""
    import importlib

    module = importlib.import_module(module_name)
    service = getattr(module, factory).__new__(getattr(module, factory))
    logged = []
    service.logger = MagicMock()
    service.logger.info = lambda message, *a, **k: logged.append(str(message))
    monkeypatch.setattr(module, "logger", service.logger, raising=False)
    service.clear_cache = lambda *a, **k: None
    service.invalidate_memory_cache_only = lambda reason=None: logged.append(str(reason))
    monkeypatch.setattr("services.infrastructure.event_manager.get_event_manager",
                        lambda: _Recorder())
    service._handle_donation_event(SimpleNamespace(data=payload,
                                                   source_service="unified_donations"))
    return " | ".join(logged)


@pytest.mark.parametrize("module_name,factory", [
    ("services.mech.mech_status_cache_service", "MechStatusCacheService"),
    ("services.mech.animation_cache_service", "AnimationCacheService"),
])
def test_a_reset_is_not_logged_as_a_completed_donation(module_name, factory, monkeypatch):
    """The visible half: what the operator reads in the log."""
    written = _handle(module_name, factory, RESET_PAYLOAD, monkeypatch)

    assert "Donation completed" not in written, (
        f"an admin reset the ledger and the log says: {written}"
    )
    assert "reset" in written.lower(), (
        f"the log does not say what happened either: {written}"
    )


@pytest.mark.parametrize("module_name,factory", [
    ("services.mech.mech_status_cache_service", "MechStatusCacheService"),
    ("services.mech.animation_cache_service", "AnimationCacheService"),
])
def test_a_real_donation_is_still_logged_as_one(module_name, factory, monkeypatch):
    """The counter-case: the amount must not disappear from the log."""
    written = _handle(module_name, factory, DONATION_PAYLOAD, monkeypatch)

    assert "25.0" in written, written
