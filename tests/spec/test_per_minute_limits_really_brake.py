# -*- coding: utf-8 -*-
"""The per-minute limits in the panel must actually brake.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. The panel offers two fields - "max. commands per minute" (20)
and "max. buttons per minute" (30). Both are saved, both are passed back
and forth cleanly via ``to_dict``/``from_dict`` - and **nobody ever
queries them**.

Measured: the two names occur in the entire application code in exactly eight
places, all in ``spam_protection_service.py`` - field description
(:28-29), reading (:40-41), writing (:53-54), defaults (:314, :325). Not a
single place compares a counter with them, and there is no counting mechanism
anywhere.

WHAT THE OPERATOR SEES OF IT: he sets "max. 30 buttons per minute",
saves, sees the value again the next time he opens it - and nothing brakes.
Exactly the kind "unnoticed", which only shows when someone tries it on
purpose.

WHY IT NEVER STOOD OUT SO FAR: there is no place where a press is COUNTED.
The per-button cooldown only remembers the LAST point in time
(``_user_cooldowns``), not the number.

WHAT IS COUNTED IS THE ACCEPTED PRESS, not the query - so in
``add_user_cooldown``, not in ``is_on_cooldown``. If the check itself
counted, a refused repetition would use up further quota, and
legitimate use would be throttled. The test below records both.

THE CLOCK, and a decision REVISITED on 2026-09-23: this file used to argue for
``time.time()`` on the grounds that a switch would leave ONE service running
two clocks - ``_user_cooldowns`` frozen by the existing tests, the window real.
That argument was against a PARTIAL switch, and it was right about that.

The whole service moved to ``time.monotonic()`` instead, because the wall clock
steps backwards: after an NTP correction of minus an hour, every button the
user had touched was on cooldown and the refusal read "please wait 3610.0
seconds", for the size of the jump, with nothing in the log
(test_a_clock_correction_does_not_lock_every_button.py). There is still only
one clock; the tests freeze ``monotonic`` now.

DIFFERENT BUTTON NAMES IN THE TEST, and that is no coincidence: every ``probe_N``
falls to the 5-second fallback rule (``get_button_cooldown:186``), and none
locks the next. What still brakes after N presses can therefore ONLY be the
per-minute limit - not the per-button cooldown.

DELIMITATION: this test changes nothing about the question which of the 13
places ask the service at all. Most keep their own cooldown bookkeeping
and never reach ``is_on_cooldown`` - a separate finding with a separate
decision. Here it is only about the limit existing in the service at all
and biting.
"""

import time

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

USER = 5150
OTHER_USER = 6270


def _service(tmp_path):
    return SpamProtectionService(config_dir=str(tmp_path))


def _fill(service, user, count, prefix="probe"):
    """Enters ``count`` accepted presses - each with its own name."""
    for i in range(count):
        service.add_user_cooldown(user, f"{prefix}_{i}")


def test_the_two_limits_differ_at_all(tmp_path):
    """Safeguard against a blunt tool.

    The tests below distinguish the button and the command limit. If both had
    the same value, a mix-up in the code could go unnoticed.
    """
    defaults = _service(tmp_path)._get_default_config()

    assert defaults.max_commands_per_minute == 20
    assert defaults.max_buttons_per_minute == 30
    assert defaults.max_commands_per_minute != defaults.max_buttons_per_minute


def test_up_to_the_limit_nothing_brakes(tmp_path):
    """Delimitation, and the more important half of the finding.

    A brake that takes effect too early would be worse than none. Exactly
    ``max_buttons_per_minute`` presses must get through - the next one not.

    THE COUNTING, explicitly, because an off-by-one error lurks here:
    with "at most 30 per minute", 30 presses are allowed and the 31st is
    refused. So this test fills ``limit - 1`` and checks that the
    ``limit``-th still gets through; the test below fills ``limit`` and checks
    that the next one is refused. Together they nail down the edge - a
    fix that lets one press too many through turns red.
    """
    service = _service(tmp_path)
    limit = service._get_default_config().max_buttons_per_minute

    _fill(service, USER, limit - 1)

    assert service.is_on_cooldown(USER, "probe_fresh") is False, (
        f"After {limit - 1} presses it already brakes, although only the "
        f"{limit + 1}th may be refused. The limit takes effect too early."
    )


def test_above_the_limit_it_brakes(tmp_path):
    """THE FINDING: the button limit from the panel does not brake."""
    service = _service(tmp_path)
    limit = service._get_default_config().max_buttons_per_minute

    _fill(service, USER, limit)

    assert service.is_on_cooldown(USER, "probe_fresh") is True, (
        f"After {limit} accepted presses in the same minute - the "
        f"quota from max_buttons_per_minute - the next one is still "
        "not refused. The panel offers the field, saves it, shows it "
        "again - and nobody queries it."
    )


def test_the_refusal_names_a_usable_remaining_time(tmp_path):
    """THE FINDING, second half: 'wait 0.0 seconds' is no information.

    All callers ask ``get_remaining_cooldown`` right after ``is_on_cooldown``.
    If that keeps computing only from ``_user_cooldowns``, the user sees 0.0 -
    because the fresh button name has no entry there at all. The remaining
    time must come from the WINDOW.
    """
    service = _service(tmp_path)
    limit = service._get_default_config().max_buttons_per_minute

    _fill(service, USER, limit)
    remaining = service.get_remaining_cooldown(USER, "probe_fresh")

    assert remaining > 0.0, (
        "The button is locked, but the reported remaining time is 0.0 - the "
        "user reads 'please wait 0.0 seconds' and still may not."
    )
    assert remaining <= 60.0, (
        f"The remaining time is {remaining}s. A one-minute window can create at most "
        "60 seconds of waiting."
    )


def test_the_window_slides(tmp_path, monkeypatch):
    """Delimitation: it is a one-minute window, not a grand total.

    Without this test a fix could simply count all presses and lock the
    user out permanently after the limit.
    """
    service = _service(tmp_path)
    limit = service._get_default_config().max_buttons_per_minute

    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    _fill(service, USER, limit)
    assert service.is_on_cooldown(USER, "probe_fresh") is True

    monkeypatch.setattr(time, "monotonic", lambda: 1061.0)
    assert service.is_on_cooldown(USER, "probe_fresh") is False, (
        "61 seconds later the per-minute limit still brakes - then it is "
        "not a sliding window but a grand total, and the user "
        "stays locked out permanently."
    )


def test_the_limit_applies_per_user(tmp_path):
    """Delimitation: one user must not lock out all others."""
    service = _service(tmp_path)
    limit = service._get_default_config().max_buttons_per_minute

    _fill(service, USER, limit + 1)

    assert service.is_on_cooldown(OTHER_USER, "probe_fresh") is False, (
        "The presses of ONE user brake another - then the window is "
        "global instead of per user, and a single user paralyzes the channel."
    )


def test_when_disabled_nothing_is_counted(tmp_path):
    """Delimitation: the operator can switch the protection off.

    If the window kept counting while the protection is off, state would
    accumulate there that locks immediately when switched back on.
    """
    from unittest.mock import patch

    service = _service(tmp_path)
    limit = service._get_default_config().max_buttons_per_minute

    with patch.object(service, "is_enabled", return_value=False):
        _fill(service, USER, limit + 5)

    assert service.is_on_cooldown(USER, "probe_fresh") is False


def test_querying_uses_no_quota(tmp_path):
    """Delimitation against the most obvious wrong fix.

    What is counted is the ACCEPTED press, not the query. If
    ``is_on_cooldown`` already counted, every refused repetition would use up
    further quota - and whoever was braked once would never get out again.
    """
    service = _service(tmp_path)
    limit = service._get_default_config().max_buttons_per_minute

    for _ in range(limit * 3):
        service.is_on_cooldown(USER, "probe_fresh")

    assert service.is_on_cooldown(USER, "probe_fresh") is False, (
        f"After {limit * 3} pure QUERIES without a single accepted "
        "press it brakes. Then the check itself counts along."
    )
