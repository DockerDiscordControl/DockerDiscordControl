# -*- coding: utf-8 -*-
"""One bad cycle must not end a background loop for the rest of the run.

THE FINDING (review E17, the first careful read of cogs/docker_control.py -
5,294 lines that no review pass ever covered, per docs/quality/COVERAGE_BY_FILE.txt).

Measured in the shipped py-cord (``ext/tasks/__init__.py``):

  * line 103  ``_valid_exception = (OSError, GatewayNotFound, ConnectionClosed,
                                    aiohttp.ClientError, asyncio.TimeoutError)``
  * line 171  only those are retried;
  * line 195  **anything else** sets ``_has_failed``, calls the loop's ``error``
              handler and re-raises - the loop is over, permanently, until DDC
              is restarted;
  * line 474  the DEFAULT error handler is a bare ``print()`` to ``sys.stderr``.

So a single ValueError, KeyError or DDC exception in a loop body stops that
loop forever, and DDC's own log never mentions it - no timestamp in DDC's
format, no logger, nothing that says "the status display is not updating any
more". The operator sees stale numbers and has nothing to look at.

Three of the eight loops had no guard of their own:

  * ``periodic_message_edit_loop``  - the status display refresh. The single
    most visible thing DDC does.
  * ``status_update_loop``          - the container status cache.
  * ``inactivity_check_loop``       - message regeneration.

and DDC registered **no** ``.error`` handler on any loop at all, so even the
guarded ones would have died in silence.

Both halves are pinned here: the body survives a bad cycle, and a loop that
dies anyway says so through the DDC logger.
"""

import logging

import pytest


@pytest.fixture
def cog():
    from cogs.docker_control import DockerControlCog
    return DockerControlCog.__new__(DockerControlCog)


def _loop(name):
    from cogs.docker_control import DockerControlCog
    return getattr(DockerControlCog, name)


# The three that had no guard of their own, named because the fix is per-loop.
UNGUARDED = ["periodic_message_edit_loop", "status_update_loop", "inactivity_check_loop"]


def _all_loops():
    """Read the loops off the class, so one added tomorrow is covered today.

    A hard-coded list would have been a snapshot of 2026-09-21 and would pass
    for ever afterwards while a new loop went unwatched. That is the difference
    between a test and a record of a test.
    """
    from discord.ext import tasks
    from cogs.docker_control import DockerControlCog
    return sorted(name for name in dir(DockerControlCog)
                  if isinstance(getattr(DockerControlCog, name, None), tasks.Loop))


ALL_LOOPS = _all_loops()


@pytest.mark.parametrize("loop_name", UNGUARDED)
@pytest.mark.asyncio
async def test_a_raising_config_does_not_end_the_loop(loop_name, cog, monkeypatch, caplog):
    """load_config is the first thing all three do, and it can raise."""
    import cogs.docker_control as docker_control
    from services.exceptions import ConfigServiceError

    def boom():
        raise ConfigServiceError("config.json is unreadable")

    monkeypatch.setattr(docker_control, "load_config", boom)

    with caplog.at_level(logging.DEBUG):
        # Must return, not raise. py-cord ends the loop on anything it raises.
        await _loop(loop_name).coro(cog)

    # The ERROR must be about THIS failure. Until 2026-09-22 any ERROR passed, and
    # the fixture's cog is incomplete: every cycle already failed on an
    # AttributeError (cache_ttl_seconds, initial_messages_sent) before or without
    # reaching load_config - so this test was green whether or not the config
    # failure was survived. Found during the Phase 3 cog split, when a moved
    # loop stopped seeing the patch below and nothing turned red.
    assert any(r.levelno >= logging.ERROR and "config.json is unreadable" in r.getMessage()
               for r in caplog.records), (
        f"{loop_name} did not report the failed config read"
    )


@pytest.mark.parametrize("loop_name", ALL_LOOPS)
def test_every_loop_says_so_when_it_dies(loop_name):
    """py-cord's default error handler is a print() to stderr. That is not enough."""
    loop = _loop(loop_name)

    assert loop._error is not None and loop._error.__name__ != "_error", (
        f"{loop_name} has no error handler of its own, so if it ever stops, "
        f"py-cord prints a traceback to stderr and DDC's log says nothing - "
        f"the operator sees stale data and has nothing to look at"
    )


@pytest.mark.asyncio
async def test_the_death_notice_names_the_loop_and_the_consequence(caplog):
    """A log line saying 'error' is not enough to act on at three in the morning."""
    loop = _loop("periodic_message_edit_loop")

    with caplog.at_level(logging.DEBUG):
        await loop._error(None, ValueError("something went wrong"))

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "the loop died and nothing was logged"
    joined = " ".join(errors)
    assert "periodic_message_edit_loop" in joined, (
        f"the notice does not say WHICH loop stopped: {joined!r}"
    )
    assert "ValueError" in joined, f"the notice does not say why: {joined!r}"


def test_the_donation_loop_is_not_forgotten():
    """It lives inside setup(), not on the class, so the class sweep misses it.

    _register_loop_error_handlers walks the cog class. check_donation_notifications
    is a local inside setup(), so it is invisible to that sweep - exactly the kind
    of loop a fix leaves behind. It gets its handler by hand, and this asks whether
    it still does.

    **This one reads the source text**, and that is weaker than the tests above:
    it would not notice a handler that is registered but broken. Running setup()
    for real needs a connected bot. What it does catch is the failure that
    actually happens - somebody edits this function and the hand-written
    registration goes away with the rest - and that is worth more than nothing.
    """
    import inspect

    import cogs.docker_control as docker_control

    source = inspect.getsource(docker_control.setup)

    assert "check_donation_notifications.error(" in source, (
        "the donation notification loop has no error handler, so if it stops, "
        "web-panel donations quietly stop being announced in Discord"
    )
    assert source.index("check_donation_notifications.error(") < \
        source.index("check_donation_notifications.start()"), (
        "the handler is registered after the loop is started - a loop that fails "
        "in its first cycle would still die the old, silent way"
    )
