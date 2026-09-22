# -*- coding: utf-8 -*-
"""Unloading the cog stops every loop it started.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 06 F3, re-checked 2026-09-20):
``cog_unload`` says of itself "Cancel all running background tasks when the
cog is unloaded" and then cancels five loops. Three more are started in
``setup()`` and never mentioned there: ``check_donation_notifications``
(kept as ``cog.donation_notification_task``), ``start_mech_cache_loop`` and
``initial_animation_cache_warmup``. After an unload they keep running against
a cog nobody uses any more - the donation loop polls every 30 s and would
announce a donation through a bot that has been taken apart.

Measured, and it belongs in the record: nothing in this project unloads or
reloads an extension - there is no ``unload_extension`` or
``reload_extension`` anywhere, and the startup loads its three extensions
once. So this is not a failure anybody has seen; it is a method that does
not do what it says, in the one place whose whole job is to leave nothing
running.
"""

from unittest.mock import MagicMock

import pytest

from cogs.docker_control import DockerControlCog

LOOPS = ("heartbeat_send_loop", "status_update_loop", "periodic_message_edit_loop",
         "inactivity_check_loop", "performance_cache_clear_loop",
         "start_mech_cache_loop", "initial_animation_cache_warmup")


def _running_loop():
    loop = MagicMock()
    loop.is_running.return_value = True
    return loop


def _cog():
    cog = object.__new__(DockerControlCog)
    for name in LOOPS:
        setattr(cog, name, _running_loop())
    cog.donation_notification_task = _running_loop()
    return cog


def test_every_loop_is_cancelled():
    cog = _cog()

    cog.cog_unload()

    still_running = [name for name in LOOPS if not getattr(cog, name).cancel.called]
    assert not still_running, f"these loops keep running after the unload: {still_running}"
    assert cog.donation_notification_task.cancel.called, (
        "the donation notification loop polls every 30 s and would announce a "
        "donation through a cog that is no longer loaded"
    )


def test_a_loop_that_is_not_running_is_left_alone():
    """Counter-check: cancelling what never started would raise on a real loop."""
    cog = _cog()
    cog.status_update_loop.is_running.return_value = False

    cog.cog_unload()

    assert not cog.status_update_loop.cancel.called


def test_a_missing_loop_does_not_break_the_unload():
    """A cog built without the optional attributes must still unload."""
    cog = _cog()
    del cog.donation_notification_task

    cog.cog_unload()  # must not raise
