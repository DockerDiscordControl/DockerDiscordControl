# -*- coding: utf-8 -*-
"""A button must brake by the BUTTON slider, even if it is named like a command.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``is_on_cooldown``, ``get_remaining_cooldown`` and
``add_user_cooldown`` decide "command or button?" via a hard-wired NAME LIST
(``_BEFEHLSNAMEN``: serverstatus, ss, control, info, help, ping, donate,
command, language, forceupdate, start, stop, restart). If a BUTTON is named
like a command, it gets the command duration and counts toward the per-minute
command window::

    button "info"     -> command /info   5 s   instead of button slider info     3 s
    button "help"     -> command /help   3 s   instead of button slider help     5 s
    button "restart"  -> command         15 s  instead of button slider restart 20 s

Affected are the info button of the control panel, InfoDropdownButton,
HelpButton and the start/stop/restart buttons. The operator sets the "info
button" slider in the panel - and the slider of the /info COMMAND brakes. The
same kind of defect as with the mech buttons (the wrong slider applies), only
via a different path.

PART OF IT IS MY OWN MISTAKE: before the switch to the service,
InfoDropdownButton and HelpButton explicitly asked ``get_button_cooldown``.
The switch (commit 3785fc0) sends them through the name list. The tests of that
commit checked the ARGUMENT ("info", "help"), not the effective duration - and
therefore did not notice.

THE FIX: all current callers of the three methods are BUTTONS (measured;
commands brake via their own path in docker_control.py). So button becomes the
default; whoever wants to brake a command says so explicitly with
``kind="command"``. The name list goes away - together with its known quirks
("ss" is in no dictionary, "donatebroadcast" and "info_edit" are missing).

HOW IT IS CHECKED HERE: at service level, because that is where the bug sits,
with a real service and a frozen clock. That is the same clock replacement the
existing tests use (``time.time`` in the module), so that service and test see
the same time.

TWO TRAPS, sealed in advance:

1. If the button and command values were equal, every duration check would be
   hollow. The first guard pins that they DIFFER for info, help and restart.
2. ``kind=`` does not exist before the fix. A call with it would be an ERROR
   (TypeError) instead of a failure. The scope test therefore checks the
   signature first and fails cleanly on an assertion.
"""

import inspect
import time

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

USER = 4411
NOW = 50_000.0


def _service(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: NOW)
    return SpamProtectionService(config_dir=str(tmp_path))


def test_button_and_command_sliders_differ(tmp_path):
    """Guard: without different values no duration check would prove anything."""
    service = SpamProtectionService(config_dir=str(tmp_path))

    for name in ("info", "help", "restart"):
        button = service.get_button_cooldown(name)
        command = service.get_command_cooldown(name)
        assert button != command, (
            f"{name!r}: button slider ({button}) and command slider ({command}) "
            "are equal - the tests below could not see the difference."
        )


@pytest.mark.parametrize("name", ["info", "help", "restart"])
def test_a_button_brakes_by_its_button_slider(tmp_path, monkeypatch, name):
    """THE FINDING: braking uses the command slider of the same name."""
    service = _service(tmp_path, monkeypatch)
    expected = service.get_button_cooldown(name)
    command = service.get_command_cooldown(name)

    service.add_user_cooldown(USER, name)
    rest = service.get_remaining_cooldown(USER, name)

    assert rest == pytest.approx(expected), (
        f"The button {name!r} is locked for {rest:.1f} s - that is the slider of the "
        f"COMMAND ({command} s), not that of the button ({expected} s). The "
        "operator sets the button slider in the panel, and it moves nothing."
    )


@pytest.mark.parametrize("name", ["info", "help", "restart"])
def test_a_button_is_free_again_after_its_button_slider(tmp_path, monkeypatch, name):
    """THE FINDING, effect: after the button duration has elapsed it must work
    again - and not before."""
    service = _service(tmp_path, monkeypatch)
    duration = service.get_button_cooldown(name)

    service.add_user_cooldown(USER, name)

    monkeypatch.setattr(time, "monotonic", lambda: NOW + duration - 0.5)
    assert service.is_on_cooldown(USER, name) is True, (
        f"{name!r} is already free again {duration - 0.5} s after the press, although "
        f"the button slider demands {duration} s."
    )
    monkeypatch.setattr(time, "monotonic", lambda: NOW + duration + 0.5)
    assert service.is_on_cooldown(USER, name) is False, (
        f"{name!r} is still locked {duration + 0.5} s after the press, although the "
        f"button slider only demands {duration} s."
    )


def test_a_button_counts_toward_the_button_minute_window(tmp_path, monkeypatch):
    """THE FINDING, second consequence: "info" currently counts toward the COMMAND window.

    29 button presses under neutral names plus one press on "info" fill the
    button quota (30) - the next button must be rejected. If "info" counts
    toward the command window, the button window stays at 29.
    """
    service = _service(tmp_path, monkeypatch)
    limit = service._get_default_config().max_buttons_per_minute

    for i in range(limit - 1):
        service.add_user_cooldown(USER, f"probe_{i}")
    service.add_user_cooldown(USER, "info")

    assert service.is_on_cooldown(USER, "probe_fresh") is True, (
        f"After {limit - 1} neutral button presses and one 'info' press, "
        "the button quota is not full - 'info' was counted toward the command "
        "window."
    )


def test_commands_keep_their_slider_when_they_say_so(tmp_path, monkeypatch):
    """Scope: a COMMAND that identifies itself as such brakes by the command
    slider. Otherwise the fix would only be an inversion of the bug.

    Signature first - without ``kind`` the call would be a TypeError, i.e. an
    error instead of a failure.
    """
    for method in ("is_on_cooldown", "get_remaining_cooldown", "add_user_cooldown"):
        params = inspect.signature(getattr(SpamProtectionService, method)).parameters
        assert "kind" in params, (
            f"{method} has no parameter 'kind' - a command cannot identify "
            "itself as such."
        )

    service = _service(tmp_path, monkeypatch)
    service.add_user_cooldown(USER, "info", kind="command")

    assert service.get_remaining_cooldown(USER, "info", kind="command") == pytest.approx(
        service.get_command_cooldown("info")
    )


def test_command_and_button_of_the_same_name_share_no_bucket(tmp_path, monkeypatch):
    """Scope: /info and the info BUTTON must not lock each other.

    As soon as commands identify themselves, it would be tempting to store both
    under "<user>:info" - then a click on the info button would lock the /info
    command and vice versa. So the commands have a key space of their own.
    """
    service = _service(tmp_path, monkeypatch)

    service.add_user_cooldown(USER, "info")
    assert service.is_on_cooldown(USER, "info", kind="command") is False, (
        "A press on the info BUTTON locks the /info COMMAND - both share "
        "one bucket."
    )

    service.add_user_cooldown(USER, "help", kind="command")
    assert service.is_on_cooldown(USER, "help") is False, (
        "The /help COMMAND locks the help BUTTON - both share one bucket."
    )


def test_a_typo_in_the_kind_fails_loudly(tmp_path, monkeypatch):
    """Scope: "befhel" must not silently count as a button.

    The callers only catch (RuntimeError, AttributeError, KeyError); a
    ValueError therefore gets through and is noticed, instead of silently
    braking a command by the button slider.
    """
    service = _service(tmp_path, monkeypatch)

    for method in (service.is_on_cooldown, service.get_remaining_cooldown,
                    service.add_user_cooldown):
        with pytest.raises(ValueError):
            method(USER, "info", kind="befhel")
