# -*- coding: utf-8 -*-
"""What the startup starts, the cog knows about - and can stop again.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 04 F3, re-checked 2026-09-20):
``_setup_background_loops`` wraps every task it starts in ``_track_task``,
which puts it into ``self._active_tasks`` and takes it out when it ends - all
but one. The one-shot initial status send is created directly, so it never
appears there: it sleeps ten seconds and then posts the overview messages,
and while it does, nothing in the cog knows it exists.

And ``_active_tasks`` was written but never read, which is why nobody
noticed. With B31 the unload finally cancels every loop it started; this
makes the tracked tasks part of that, so the set means something and the
odd one out is in it.
"""

from unittest.mock import MagicMock

import pytest

from cogs.docker_control import DockerControlCog

LOOPS = ("status_update_loop", "periodic_message_edit_loop", "inactivity_check_loop",
         "performance_cache_clear_loop", "heartbeat_send_loop",
         "start_mech_cache_loop", "initial_animation_cache_warmup")


def _cog(recorded):
    cog = object.__new__(DockerControlCog)
    cog.bot = MagicMock()

    def create_task(coro, *args, **kwargs):
        recorded.append(coro.cr_code.co_name)
        coro.close()  # nothing is actually run here
        return MagicMock()

    cog.bot.loop.create_task = create_task
    cog.update_global_status_cache = MagicMock()
    for name in LOOPS:
        setattr(cog, name, MagicMock())
    return cog


def test_the_setup_starts_something_at_all():
    """Guard against a blunt test: an empty list would pass trivially."""
    recorded = []
    _cog(recorded)._setup_background_loops()

    assert len(recorded) >= 6, recorded
    assert "send_initial_after_delay" in recorded, recorded


def test_every_started_task_is_tracked():
    recorded = []
    _cog(recorded)._setup_background_loops()

    tracked = recorded.count("_track_task")
    started = len(recorded) - tracked
    assert tracked == started, (
        f"{started} tasks started, {tracked} of them tracked: {recorded}"
    )


def test_unloading_cancels_the_tracked_tasks():
    cog = object.__new__(DockerControlCog)
    for name in LOOPS:
        loop = MagicMock()
        loop.is_running.return_value = True
        setattr(cog, name, loop)
    cog.donation_notification_task = MagicMock()
    cog.donation_notification_task.is_running.return_value = True
    task = MagicMock()
    task.done.return_value = False
    cog._active_tasks = {task}

    cog.cog_unload()

    assert task.cancel.called, (
        "a task the cog started itself keeps running after the unload"
    )


def test_a_finished_task_is_left_alone():
    """Counter-check: cancelling what has already ended is pointless noise."""
    cog = object.__new__(DockerControlCog)
    for name in LOOPS:
        loop = MagicMock()
        loop.is_running.return_value = False
        setattr(cog, name, loop)
    task = MagicMock()
    task.done.return_value = True
    cog._active_tasks = {task}

    cog.cog_unload()

    assert not task.cancel.called
