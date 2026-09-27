# -*- coding: utf-8 -*-
"""Guessing the protected-info password is braked per hour, not only per minute.

THE FINDING (Discord-input audit, 2026-09-26, F7): three tries per minute per
person - about 4,300 guesses a day for one account, more with several. The
minute brake stays (typos should not wait an hour); on top of it a person gets
ten tries per hour. A correct password still clears both.

HOW THIS TEST CAN FAIL: it spreads tries so the minute brake never bites and
counts how many an hour allows; and it checks a correct password frees the
person again.

COUNTER-CHECK (2026-09-27): red before - sixty tries an hour went through.
"""

import cogs.enhanced_info_modal_simple as modal


def _tries(monkeypatch, user, count, spacing):
    clock = [1_000_000.0]
    monkeypatch.setattr(modal.time, "time", lambda: clock[0])
    allowed = 0
    for _ in range(count):
        ok, _wait = modal._password_attempt_allowed(user)
        allowed += ok
        clock[0] += spacing
    return allowed


def test_an_hour_allows_ten_tries(monkeypatch):
    modal._PASSWORD_ATTEMPTS.clear()
    assert _tries(monkeypatch, 1, 60, 61) == 10  # one a minute: the minute brake never bites


def test_a_correct_password_frees_the_person(monkeypatch):
    modal._PASSWORD_ATTEMPTS.clear()
    _tries(monkeypatch, 2, 10, 61)
    modal._clear_password_attempts(2)
    assert _tries(monkeypatch, 2, 1, 61) == 1


def test_the_minute_brake_still_holds(monkeypatch):
    modal._PASSWORD_ATTEMPTS.clear()
    assert _tries(monkeypatch, 3, 5, 1) == 3
