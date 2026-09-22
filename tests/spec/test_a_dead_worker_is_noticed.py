# -*- coding: utf-8 -*-
"""
THE FINDING (review C41, section 34 F2 and F3): two background workers in
`app/utils/web_helpers.py` can die quietly and never come back. Two findings in
one commit on purpose - they are the same statement about two twin loops in one
file, and one test file covers them.

F2 - the Docker cache refresh worker. `start_background_refresh()` already asks
     whether the thread is alive before starting a new one, but the caller that
     would REACH it does not:

         if ENABLE_BACKGROUND_REFRESH and not docker_cache['bg_refresh_running'] \\
                 and not background_refresh_thread:
             start_background_refresh(logger)

     A thread that has died is not None - it is simply finished - so
     `not background_refresh_thread` is False and the restart never happens.
     The panel keeps working, but only through the synchronous fallback, which
     runs a blocking Docker query of up to 30 seconds inside whichever web
     request happens to hit a stale cache.

F3 - the mech decay worker. Its inner clause catches
     (ImportError, AttributeError, RuntimeError) and its outer one
     (AttributeError, RuntimeError), while its twin above catches
     (ValueError, TypeError, KeyError) as well. Anything else - a KeyError from
     the progress state, an OSError, any DDC exception - falls through both and
     lands in the `finally`, which logs "Mech decay background worker stopped"
     at INFO: the exact line a deliberate, healthy stop produces. Nothing
     restarts it, so mech power decay is no longer pre-computed until the whole
     process restarts, and the log says everything is fine.

The counter-checks keep both ends: a worker that is alive is not restarted, and
a clean stop still reads as a clean stop.
"""

import logging
import threading

import pytest

from app.utils import web_helpers as wh


class _DeadThread:
    """A thread object that has finished - not None, just over."""
    dead = True
    name = "DockerCacheRefresh"

    @staticmethod
    def is_alive():
        return False


class _LiveThread:
    dead = False
    name = "DockerCacheRefresh"

    @staticmethod
    def is_alive():
        return True


@pytest.fixture
def quiet_cache(monkeypatch):
    fresh = {
        'global_timestamp': None, 'containers': [], 'error': None,
        'container_timestamps': {}, 'container_hashes': {},
        'bg_refresh_running': False, 'priority_containers': set(),
        'last_cleanup': None, 'access_count': 0,
    }
    monkeypatch.setattr(wh, "docker_cache", fresh)
    monkeypatch.setattr(wh, "ENABLE_BACKGROUND_REFRESH", True)
    monkeypatch.setattr(wh, "update_docker_cache", lambda logger: None)
    return fresh


def test_a_refresh_worker_that_died_is_started_again(quiet_cache, monkeypatch):
    """F2: a finished thread is not a running one."""
    started = []
    monkeypatch.setattr(wh, "background_refresh_thread", _DeadThread())
    monkeypatch.setattr(wh, "start_background_refresh", lambda logger: started.append(True))

    wh.get_docker_containers_live(logging.getLogger("ddc.spec"))

    assert started == [True], "the dead worker was never restarted"


def test_a_living_refresh_worker_is_left_alone(quiet_cache, monkeypatch):
    """COUNTER-CHECK: no restart storm for a healthy worker."""
    started = []
    monkeypatch.setattr(wh, "background_refresh_thread", _LiveThread())
    monkeypatch.setattr(wh, "start_background_refresh", lambda logger: started.append(True))

    wh.get_docker_containers_live(logging.getLogger("ddc.spec"))

    assert started == []


def _run_decay_once(monkeypatch, failure):
    """Let the decay worker take exactly one turn, which fails."""
    calls = {"n": 0}

    def _get_progress_service():
        calls["n"] += 1
        wh.stop_mech_decay_thread.set()      # stop after this turn
        raise failure

    module = type(wh)("services.mech.progress_service")
    module.get_progress_service = _get_progress_service
    import sys
    monkeypatch.setitem(sys.modules, "services.mech.progress_service", module)
    monkeypatch.setattr(wh, "MECH_DECAY_INTERVAL", 0)
    wh.stop_mech_decay_thread.clear()
    return calls


def test_the_decay_worker_reports_an_unexpected_error(monkeypatch, caplog):
    """F3: a KeyError must not read like a healthy shutdown."""
    _run_decay_once(monkeypatch, KeyError("power_current"))

    with caplog.at_level(logging.DEBUG):
        wh.mech_decay_worker(logging.getLogger("ddc.spec.decay"))

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "the worker died and the log said 'stopped', like a clean stop"


def test_the_decay_worker_keeps_going_after_one_bad_turn(monkeypatch, caplog):
    """F3, the half that matters more: an error on one turn must not end the
    worker. It has to come round again."""
    import sys
    calls = {"n": 0}

    class _State:
        is_offline = False
        power_current = 5.0

    def _get_progress_service():
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyError("power_current")
        wh.stop_mech_decay_thread.set()
        return type("S", (), {"get_state": staticmethod(lambda: _State())})()

    module = type(wh)("services.mech.progress_service")
    module.get_progress_service = _get_progress_service
    monkeypatch.setitem(sys.modules, "services.mech.progress_service", module)
    monkeypatch.setattr(wh, "MECH_DECAY_INTERVAL", 0)
    wh.stop_mech_decay_thread.clear()

    with caplog.at_level(logging.DEBUG):
        wh.mech_decay_worker(logging.getLogger("ddc.spec.decay"))

    assert calls["n"] == 2, "the worker stopped after the first error"


def test_a_clean_stop_is_still_a_clean_stop(monkeypatch, caplog):
    """COUNTER-CHECK: stopping on purpose must not look like a crash."""
    import sys
    module = type(wh)("services.mech.progress_service")

    class _State:
        is_offline = False
        power_current = 5.0

    module.get_progress_service = lambda: type("S", (), {"get_state": staticmethod(lambda: _State())})()
    monkeypatch.setitem(sys.modules, "services.mech.progress_service", module)
    monkeypatch.setattr(wh, "MECH_DECAY_INTERVAL", 0)
    wh.stop_mech_decay_thread.set()

    with caplog.at_level(logging.DEBUG):
        wh.mech_decay_worker(logging.getLogger("ddc.spec.decay"))

    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
