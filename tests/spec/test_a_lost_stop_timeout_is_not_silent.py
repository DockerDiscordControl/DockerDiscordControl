# -*- coding: utf-8 -*-
"""
THE FINDING (review E50): `get_stop_timeout_kwargs` returns `{}` for two
completely different reasons, and its caller cannot tell them apart.

    try:
        stop_timeout = (container.attrs.get('Config') or {}).get('StopTimeout')
    except (AttributeError, TypeError):
        return {}

`{}` means "no StopTimeout is configured, let docker-py use its defaults" -
and the docstring says so. The handler returns the same `{}` when the
container object could not be read at all, and says nothing.

What `{}` costs is in the docstring too: docker-py's `restart()` defaults to
`timeout=10`, which OVERRIDES the container's configured StopTimeout. This
function is on every stop and every restart there is -

    docker_action_service.py:94-95   the buttons and the admin overview
    docker_utils.py:714-715          the same two, the other way in
    scheduler.py:1667                the scheduled tasks, which also read the
                                     value back to show it

- so if `container.attrs` ever stops being readable (a docker-py rename, a
  stub object, a container fetched a different way), every game server on the
  install silently drops to a ten-second stop. Valheim, Satisfactory and
  V-Rising all write their world on shutdown. The operator loses a save, and
  there is not one line anywhere that points at DDC.

The probability is low. The damage is a lost world and a diagnosis nobody can
make. The fix is that the silent branch stops being silent.

The counter-check keeps the meaning that is right: a container with no
StopTimeout configured is the ordinary case and must stay quiet.
"""

import logging

import pytest

from services.docker_service.docker_action_service import get_stop_timeout_kwargs


class _Unreadable:
    """A container object whose attrs cannot be read - the handler's branch."""

    name = "valheim"

    @property
    def attrs(self):
        raise AttributeError("'Container' object has no attribute 'attrs'")


class _Configured:
    """The ordinary container, with a StopTimeout its world needs."""

    name = "satisfactory"
    attrs = {"Config": {"StopTimeout": 120}}


class _Plain:
    """The ordinary container without one."""

    name = "adguard"
    attrs = {"Config": {}}


def test_an_unreadable_container_says_so(caplog):
    """THE FINDING: falling back to a ten-second stop must not be silent."""
    with caplog.at_level(logging.DEBUG):
        result = get_stop_timeout_kwargs(_Unreadable())

    assert result == {}, "the fallback itself is right - it is the silence that is not"

    complaints = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert complaints, (
        "the container's stop timeout could not be read and nothing was said; "
        "every stop and restart goes through here"
    )
    assert any("valheim" in r.getMessage().lower() for r in complaints), (
        "the warning does not name the container it is about"
    )


def test_a_configured_timeout_is_still_passed_through(caplog):
    """COUNTER-CHECK: the value that matters still arrives."""
    with caplog.at_level(logging.DEBUG):
        result = get_stop_timeout_kwargs(_Configured())

    assert result == {"timeout": 120}
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_no_configured_timeout_stays_quiet(caplog):
    """COUNTER-CHECK: the ordinary case is not a warning. A log line on every
    stop of every container is the same as no log line at all."""
    with caplog.at_level(logging.DEBUG):
        result = get_stop_timeout_kwargs(_Plain())

    assert result == {}
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "a container without a StopTimeout is normal, not a problem"
    )
