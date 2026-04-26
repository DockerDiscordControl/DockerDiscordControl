# -*- coding: utf-8 -*-
"""
Unit tests for SchedulerService.

Covers the *real* SchedulerService API: singleton access, get_service_stats,
standalone vs. hosted start/stop modes, supervised loop cancellation, and the
double-start / stop-without-start guard rails.
"""

# ---------------------------------------------------------------------------
# Path / import fix-up: pytest places ``tests/unit/services`` on sys.path so
# the ``tests/unit/services/docker/`` test package shadows the real ``docker``
# PyPI package (because Python 3 treats ``docker/`` without ``__init__.py``
# anywhere on the path as a namespace package, and the test stub *does* have
# an ``__init__.py``). Force the genuine ``docker`` package (and its
# ``docker.client`` submodule) into ``sys.modules`` BEFORE the production
# scheduler_service is imported, otherwise collection fails with
# ``ModuleNotFoundError: No module named 'docker.client'``.
# ---------------------------------------------------------------------------
import sys as _sys
import importlib as _importlib
import importlib.util as _importlib_util
from pathlib import Path as _Path

# Drop any pre-cached (namespace) ``docker`` modules so we can rebind cleanly.
for _name in [n for n in list(_sys.modules) if n == "docker" or n.startswith("docker.")]:
    del _sys.modules[_name]

# Locate a real ``docker`` package on a site-packages-like entry and load it
# explicitly via importlib. This bypasses sys.path resolution entirely so the
# test-package shadow does not matter.
_real_docker_path = None
for _entry in _sys.path:
    _candidate = _Path(_entry) / "docker" / "__init__.py"
    if _candidate.is_file():
        # Skip the ``tests/unit/services/docker`` shadow if it ever grew an
        # __init__.py (it currently has one but no submodules).
        try:
            _candidate.relative_to(_Path(__file__).resolve().parent.parent.parent.parent)
            # path is inside the test tree -> not a real install
            continue
        except ValueError:
            _real_docker_path = _candidate
            break

if _real_docker_path is not None:
    _spec = _importlib_util.spec_from_file_location(
        "docker",
        str(_real_docker_path),
        submodule_search_locations=[str(_real_docker_path.parent)],
    )
    _docker_module = _importlib_util.module_from_spec(_spec)
    _sys.modules["docker"] = _docker_module
    _spec.loader.exec_module(_docker_module)
    # Eagerly import docker.client so later ``import docker.client`` finds it.
    _importlib.import_module("docker.client")

# ---------------------------------------------------------------------------
# Now safe to import the production code under test.
# ---------------------------------------------------------------------------
import asyncio
import threading
import time
from unittest.mock import patch

import pytest

from services.scheduling.scheduler_service import (  # noqa: E402
    SchedulerService,
    get_scheduler_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def service():
    """Fresh SchedulerService instance, fully stopped after the test."""
    svc = SchedulerService()
    yield svc
    # Best-effort teardown — never let a stray service leak into the next test.
    try:
        if svc.running:
            svc.stop()
    except Exception:  # pragma: no cover - defensive teardown
        pass


@pytest.fixture(autouse=True)
def _patch_load_tasks():
    """Stop the service loop from hitting the real task store."""
    with patch("services.scheduling.scheduler_service.load_tasks", return_value=[]):
        yield


# ===========================================================================
# Singleton pattern
# ===========================================================================
class TestSingleton:
    def test_get_scheduler_service_returns_same_instance(self):
        a = get_scheduler_service()
        b = get_scheduler_service()
        assert a is b
        assert isinstance(a, SchedulerService)


# ===========================================================================
# get_service_stats()
# ===========================================================================
class TestServiceStats:
    def test_stats_keys_present(self, service):
        stats = service.get_service_stats()
        for key in (
            "running",
            "active_tasks_count",
            "last_check_time",
            "check_interval",
            "max_concurrent_tasks",
            "task_batch_size",
            "total_executed",
            "total_skipped",
            "last_batch_size",
            "avg_execution_time",
        ):
            assert key in stats, f"missing stats key: {key}"

    def test_stats_initial_values(self, service):
        stats = service.get_service_stats()
        assert stats["running"] is False
        assert stats["active_tasks_count"] == 0
        assert stats["last_check_time"] is None
        assert stats["total_executed"] == 0
        assert stats["total_skipped"] == 0
        assert isinstance(stats["check_interval"], int)
        assert isinstance(stats["max_concurrent_tasks"], int)
        assert isinstance(stats["task_batch_size"], int)


# ===========================================================================
# Standalone mode (no running asyncio loop)
# ===========================================================================
class TestStandaloneMode:
    def test_start_spawns_thread_and_owns_loop(self, service):
        assert service.start() is True
        try:
            # Give the thread a moment to enter its loop.
            time.sleep(0.2)
            assert service.running is True
            assert service._owns_event_loop is True
            assert service.thread is not None
            assert service.thread.is_alive()
            assert service._service_task is None
        finally:
            assert service.stop() is True

        # After stop the thread is cleared and running flips to False.
        assert service.running is False
        assert service.thread is None

    def test_start_then_stop_clears_state(self, service):
        service.start()
        time.sleep(0.2)
        service.stop()
        # ``_run_service`` flips running=False in its finally block; allow a
        # tick for the thread to fully unwind.
        time.sleep(0.1)
        assert service.running is False


# ===========================================================================
# Hosted mode (already inside asyncio.run())
# ===========================================================================
class TestHostedMode:
    @pytest.mark.asyncio
    async def test_start_attaches_to_running_loop(self, service):
        running_loop = asyncio.get_running_loop()
        assert service.start() is True
        try:
            assert service.running is True
            assert service._owns_event_loop is False
            assert service.thread is None
            assert service.event_loop is running_loop
            assert isinstance(service._service_task, asyncio.Task)
            # Let the supervised loop tick at least once.
            await asyncio.sleep(0.2)
            assert not service._service_task.done()
        finally:
            assert service.stop() is True
            # ``stop`` schedules the cancellation via call_soon_threadsafe;
            # await the task so the cancellation actually propagates before
            # the test function returns.
            # ``service._service_task`` is None'd by stop(); capture before.
            await asyncio.sleep(0.1)
        assert service.running is False


# ===========================================================================
# _service_loop_supervised: clean cancellation handling
# ===========================================================================
class TestSupervisedLoop:
    @pytest.mark.asyncio
    async def test_supervised_loop_swallows_cancellation(self, service):
        """CancelledError must not escape; running flips to False in finally."""
        service.running = True

        async def _fake_service_loop():
            # Simulate ``await asyncio.sleep(...)`` getting cancelled by stop().
            await asyncio.sleep(10)

        # Patch the inner loop so we don't need real tasks.
        with patch.object(service, "_service_loop", side_effect=_fake_service_loop):
            task = asyncio.get_running_loop().create_task(
                service._service_loop_supervised()
            )
            # Let the supervised loop start awaiting.
            await asyncio.sleep(0.05)
            task.cancel()
            # Critical: awaiting must NOT raise CancelledError back at us.
            await task

        assert task.done()
        # The supervisor did not propagate the cancellation outward.
        assert task.cancelled() is False
        assert service.running is False
        assert service.event_loop is None
        assert service._service_task is None


# ===========================================================================
# Guard rails: double start / stop without start
# ===========================================================================
class TestGuardRails:
    def test_double_start_returns_false(self, service):
        assert service.start() is True
        try:
            time.sleep(0.1)
            # Second start while running — must short-circuit.
            assert service.start() is False
        finally:
            service.stop()

    def test_stop_without_start_returns_false(self, service):
        # No prior start: nothing to stop.
        assert service.running is False
        assert service.stop() is False
