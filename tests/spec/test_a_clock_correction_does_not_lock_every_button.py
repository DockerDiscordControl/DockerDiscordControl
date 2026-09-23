# -*- coding: utf-8 -*-
"""A clock that steps backwards does not lock every button for an hour.

THE FINDING (independent review of the donation path, 2026-09-23): the spam
protection measures everything with ``time.time()``, the wall clock, and has no
monotonic fallback. The wall clock does step backwards - an NTP correction
after a container starts with a drifted clock is the ordinary case, and the
step can be seconds or hours.

After a correction of, say, minus one hour:

* ``current_time - last_used`` is about -3600, which is less than any cooldown,
  so EVERY button and EVERY command is on cooldown;
* ``get_remaining_cooldown`` answers ``max(0, 60 - (-3600))`` = 3660, so the
  user is told "⏰ Please wait 3660.0 more seconds before using this button
  again";
* ``_prune_window``'s cutoff is ``now - 60``, and every timestamp in the bucket
  is larger than that, so nothing is ever pruned and the per-minute limit stays
  reached.

It lasts as long as the jump and nothing is written to the log. MEASURED, and
narrower than the review said: a button nobody has pressed yet is NOT affected,
because its last-used time defaults to 0 and the difference stays large. What
is affected is every button and command the user HAS used - which after a
minute of ordinary work is all of the ones they reach for.

A monotonic clock cannot step backwards. Nothing here is persisted or compared
across restarts: both stores are in memory, so the change is confined.

HOW THIS TEST CAN FAIL: it records a press, steps the WALL clock back an hour,
and reads what the user would be told. A number larger than the cooldown is
red.

COUNTER-CHECK (2026-09-23): red before - 3660.0 seconds, and every button on
cooldown. The other tests keep the brake working: a press really is on
cooldown, it really does expire, and the per-minute window still bites and
still lets go.
"""

import time

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

USER = 4242
BUTTON = "mech_donate_1"


@pytest.fixture
def service(tmp_path):
    return SpamProtectionService(config_dir=str(tmp_path))


@pytest.fixture
def clock_jumps_back(monkeypatch):
    """The wall clock steps back one hour, as after an NTP correction."""
    real_time = time.time
    offset = {"seconds": 0.0}

    monkeypatch.setattr(time, "time", lambda: real_time() + offset["seconds"])
    return lambda seconds: offset.__setitem__("seconds", seconds)


def test_the_user_is_not_told_to_wait_an_hour(service, clock_jumps_back):
    """THE FINDING: '⏰ Please wait 3660.0 more seconds'."""
    service.add_user_cooldown(USER, BUTTON)
    clock_jumps_back(-3600)

    remaining = service.get_remaining_cooldown(USER, BUTTON)

    assert remaining <= 60, (
        f"the user is told to wait {remaining:.1f} seconds because the clock "
        "was corrected backwards")


def test_the_jump_changes_nothing_for_any_button_the_user_touched(service, clock_jumps_back):
    """The correct behaviour is not "free" - it is "unaffected".

    A press a moment ago is still on cooldown, and rightly so; what must not
    happen is that the wait GROWS by the size of the jump. Written the other
    way round first ("free again"), which was the test mirroring a wish
    instead of the contract.
    """
    for name in (BUTTON, "mech_display_3"):
        service.add_user_cooldown(USER, name)
    service.add_user_cooldown(USER, "ss", kind="command")
    clock_jumps_back(-3600)

    too_long = {name: service.get_remaining_cooldown(USER, name)
                for name in (BUTTON, "mech_display_3")
                if service.get_remaining_cooldown(USER, name) > 60}
    if service.get_remaining_cooldown(USER, "ss", kind="command") > 60:
        too_long["ss"] = service.get_remaining_cooldown(USER, "ss", kind="command")

    assert too_long == {}, (
        f"the backwards clock step added its whole size to the wait: {too_long}")


def test_a_press_is_still_on_cooldown(service):
    """Counter-check: the brake must still brake."""
    service.add_user_cooldown(USER, BUTTON)

    assert service.is_on_cooldown(USER, BUTTON) is True
    assert service.get_remaining_cooldown(USER, BUTTON) > 0


def test_a_cooldown_still_expires(service, monkeypatch):
    """Counter-check: and it must let go again."""
    import services.infrastructure.spam_protection_service as module

    now = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    service.add_user_cooldown(USER, BUTTON)
    assert service.is_on_cooldown(USER, BUTTON) is True

    now[0] += 3600

    assert service.is_on_cooldown(USER, BUTTON) is False
    assert service.get_remaining_cooldown(USER, BUTTON) == 0.0


def test_the_per_minute_window_still_bites_and_still_lets_go(service, monkeypatch):
    """Counter-check: the other half of the brake."""
    import services.infrastructure.spam_protection_service as module

    now = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    limit = service._minute_limit(False)
    for _ in range(limit):
        service._record_in_window(USER, False, module.time.monotonic())

    assert service._window_exceeded(USER, False, module.time.monotonic()) is True

    now[0] += 61

    assert service._window_exceeded(USER, False, module.time.monotonic()) is False
