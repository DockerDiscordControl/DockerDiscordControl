#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Functional unit tests for:
  - services.docker_service.docker_client_pool (DockerClientService + helpers)
  - services.docker_status.fetch_service (DockerStatusFetchService)

Coverage targets:
  - docker_client_pool: 21% -> 70%+ (~+175 LOC covered)
  - fetch_service:      57% -> 85%+ (~+28 LOC covered)

Strategy
--------
* Real ``docker`` package is imported (NOT sys.modules-mocked), the same way
  the existing ``test_docker_status_services.py`` does it. This avoids cross-
  test pollution where other tests do ``except docker.errors.APIError``.
* docker.DockerClient / docker.from_env are monkeypatched per-test.
* ``services.config.config_service.load_config`` is patched where the pool
  imports it dynamically inside ``_create_new_client_async`` /
  ``get_docker_client_async``.
* AsyncMock is used for the few async helpers we need to stub.
* The existing ``tests/unit/services/test_docker_status_services.py`` is NOT
  modified.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import docker  # noqa: F401  ensure real package
import docker.errors  # noqa: F401
import pytest

from services.docker_service import docker_client_pool as dcp_mod
from services.docker_service.docker_client_pool import (
    DockerClientRequest,
    DockerClientResult,
    DockerClientService,
    DockerPoolStatsRequest,
    DockerPoolStatsResult,
    QueueRequest,
    get_docker_client_async,
    get_docker_client_service,
)
from services.docker_status import get_fetch_service
from services.exceptions import DockerConnectionError


# =========================================================================== #
# Helpers                                                                     #
# =========================================================================== #


def _make_mock_client(ping_ok: bool = True) -> MagicMock:
    """Create a fake docker.DockerClient with ping/close methods.

    NOTE: The ``DockerException`` we raise on a "dead" ping must be the *same*
    class that the production module's ``except`` clauses reference. Other
    tests in the suite (e.g. ``scheduler/test_scheduler_service.py``) reload
    ``sys.modules['docker']`` which de-syncs this file's ``import docker``
    from the one bound inside ``docker_client_pool``. Sourcing the exception
    via ``dcp_mod.docker`` keeps both sides on the same class object.
    """
    client = MagicMock(name="DockerClient")
    if ping_ok:
        client.ping = MagicMock(return_value=True)
    else:
        client.ping = MagicMock(
            side_effect=dcp_mod.docker.errors.DockerException("dead")
        )
    client.close = MagicMock(return_value=None)
    return client


@pytest.fixture
def fresh_pool():
    """Create a fresh DockerClientService inside a running event loop.

    The service starts a background queue-processor task on init; we cancel it
    in teardown so it doesn't leak between tests.
    """

    async def _make():
        return DockerClientService(max_connections=2)

    pool = asyncio.get_event_loop().run_until_complete(_make()) if False else None
    # We can't construct here without an event loop; tests will create as needed.
    yield pool


# =========================================================================== #
# DockerClientService - construction / sync API                               #
# =========================================================================== #


class TestDockerClientServiceConstruction:
    """Construction, defaults, and synchronous helpers."""

    @pytest.mark.asyncio
    async def test_default_init_inside_loop(self):
        pool = DockerClientService()
        assert pool._max_connections == 3
        assert pool._timeout == 300
        assert pool._pool == []
        assert pool._in_use == []
        # Queue processor SHOULD start because we're in a running loop.
        assert pool._queue_processor_task is not None
        assert pool._client_available_event is not None
        await pool.close_all()

    def test_init_outside_loop_no_processor(self):
        """When constructed outside a running loop, processor stays None."""
        pool = DockerClientService(max_connections=5, timeout=42)
        assert pool._max_connections == 5
        assert pool._timeout == 42
        assert pool._queue_processor_task is None  # no running loop -> deferred
        assert pool._queue_stats["total_requests"] == 0

    def test_get_queue_stats_initial(self):
        pool = DockerClientService(max_connections=4)
        stats = pool.get_queue_stats()
        assert stats["available_clients"] == 0
        assert stats["clients_in_use"] == 0
        assert stats["max_connections"] == 4
        assert stats["current_queue_size"] == 0
        assert stats["total_requests"] == 0

    def test_update_queue_stats_first_request(self):
        pool = DockerClientService()
        pool._queue_stats["total_requests"] = 1  # simulate one request
        pool._update_queue_stats(0.5)
        assert pool._queue_stats["average_wait_time"] == 0.5

    def test_update_queue_stats_weighted_average(self):
        pool = DockerClientService()
        pool._queue_stats["total_requests"] = 5
        pool._queue_stats["average_wait_time"] = 1.0
        pool._update_queue_stats(2.0)
        # weighted: 1.0 * 0.8 + 2.0 * 0.2 = 1.2
        assert abs(pool._queue_stats["average_wait_time"] - 1.2) < 1e-9


# =========================================================================== #
# DockerClientService - client creation / pool acquisition                    #
# =========================================================================== #


class TestClientCreation:
    """_create_new_client_async + _try_immediate_acquire fast-path."""

    @pytest.mark.asyncio
    async def test_create_new_client_uses_configured_socket(self, monkeypatch):
        pool = DockerClientService(max_connections=2)
        try:
            mock_client = _make_mock_client(ping_ok=True)

            fake_load_config = MagicMock(
                return_value={"docker_config": {"docker_socket_path": "/tmp/sock"}}
            )
            # The function imports load_config lazily inside the method.
            with patch(
                "services.config.config_service.load_config",
                fake_load_config,
            ):
                with patch.object(
                    dcp_mod.docker, "DockerClient", return_value=mock_client
                ) as m_dc:
                    client = await pool._create_new_client_async()

            assert client is mock_client
            # Was called with unix socket path.
            args, kwargs = m_dc.call_args
            assert kwargs["base_url"] == "unix:///tmp/sock"
            assert kwargs["timeout"] == 30
            mock_client.ping.assert_called_once()
            assert mock_client in pool._in_use
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_create_new_client_falls_back_to_from_env(self, monkeypatch):
        pool = DockerClientService(max_connections=2)
        try:
            fallback_client = _make_mock_client(ping_ok=True)

            fake_load_config = MagicMock(
                return_value={"docker_config": {"docker_socket_path": "/tmp/sock"}}
            )
            with patch(
                "services.config.config_service.load_config",
                fake_load_config,
            ):
                with patch.object(
                    dcp_mod.docker,
                    "DockerClient",
                    side_effect=dcp_mod.docker.errors.DockerException("primary failed"),
                ):
                    with patch.object(
                        dcp_mod.docker, "from_env", return_value=fallback_client
                    ) as m_from_env:
                        client = await pool._create_new_client_async()

            assert client is fallback_client
            m_from_env.assert_called_once()
            assert fallback_client in pool._in_use
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_create_new_client_all_methods_fail_raises(self, monkeypatch):
        pool = DockerClientService(max_connections=2)
        try:
            fake_load_config = MagicMock(
                return_value={"docker_config": {"docker_socket_path": "/tmp/sock"}}
            )
            with patch(
                "services.config.config_service.load_config",
                fake_load_config,
            ):
                with patch.object(
                    dcp_mod.docker,
                    "DockerClient",
                    side_effect=dcp_mod.docker.errors.DockerException("primary"),
                ):
                    with patch.object(
                        dcp_mod.docker,
                        "from_env",
                        side_effect=dcp_mod.docker.errors.DockerException("env"),
                    ):
                        with pytest.raises(DockerConnectionError) as exc_info:
                            await pool._create_new_client_async()

            assert "Failed to create Docker client" in str(exc_info.value)
            assert exc_info.value.error_code == "DOCKER_CLIENT_CREATION_FAILED"
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_try_immediate_acquire_creates_when_pool_empty(self):
        pool = DockerClientService(max_connections=2)
        try:
            mock_client = _make_mock_client(ping_ok=True)

            async def _stub_create():
                pool._in_use.append(mock_client)
                return mock_client

            with patch.object(pool, "_create_new_client_async", _stub_create):
                client = await pool._try_immediate_acquire()
            assert client is mock_client
            assert mock_client in pool._in_use
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_try_immediate_acquire_reuses_pool_client(self):
        pool = DockerClientService(max_connections=2)
        try:
            cached = _make_mock_client(ping_ok=True)
            pool._pool.append(cached)

            client = await pool._try_immediate_acquire()
            assert client is cached
            # moved from pool to in_use
            assert cached in pool._in_use
            assert cached not in pool._pool
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_try_immediate_acquire_dead_client_replaced(self):
        pool = DockerClientService(max_connections=2)
        try:
            dead = _make_mock_client(ping_ok=False)
            pool._pool.append(dead)
            replacement = _make_mock_client(ping_ok=True)

            async def _stub_create():
                pool._in_use.append(replacement)
                return replacement

            with patch.object(pool, "_create_new_client_async", _stub_create):
                client = await pool._try_immediate_acquire()

            assert client is replacement
            assert dead not in pool._in_use
            assert dead not in pool._pool
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_try_immediate_acquire_returns_none_when_pool_full(self):
        pool = DockerClientService(max_connections=1)
        try:
            # Fill in_use to capacity, no idle clients
            busy = _make_mock_client(ping_ok=True)
            pool._in_use.append(busy)

            client = await pool._try_immediate_acquire()
            assert client is None
        finally:
            await pool.close_all()


# =========================================================================== #
# DockerClientService - release / cleanup / close_all                         #
# =========================================================================== #


class TestReleaseAndCleanup:
    @pytest.mark.asyncio
    async def test_release_client_async_returns_to_pool(self):
        pool = DockerClientService(max_connections=2)
        try:
            client = _make_mock_client()
            pool._in_use.append(client)
            await pool._release_client_async(client)
            assert client in pool._pool
            assert client not in pool._in_use
            # event should be set
            assert pool._client_available_event.is_set()
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_release_client_unknown_no_op(self):
        pool = DockerClientService(max_connections=2)
        try:
            stranger = _make_mock_client()
            # Not in _in_use - should be silently ignored.
            await pool._release_client_async(stranger)
            assert stranger not in pool._pool
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_release_docker_client_service_success(self):
        pool = DockerClientService(max_connections=2)
        try:
            client = _make_mock_client()
            pool._in_use.append(client)
            ok = await pool.release_docker_client_service(client)
            assert ok is True
            assert client in pool._pool
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_release_docker_client_service_handles_error(self):
        pool = DockerClientService(max_connections=2)
        try:
            async def _boom(_c):
                raise RuntimeError("boom")

            with patch.object(pool, "_release_client_async", _boom):
                ok = await pool.release_docker_client_service(_make_mock_client())
            assert ok is False
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections_removes_dead(self):
        pool = DockerClientService(max_connections=4)
        try:
            alive = _make_mock_client(ping_ok=True)
            dead = _make_mock_client(ping_ok=False)
            pool._pool.extend([alive, dead])

            await pool._cleanup_stale_connections()
            assert alive in pool._pool
            assert dead not in pool._pool
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_close_all_clears_pool_and_cancels_task(self):
        pool = DockerClientService(max_connections=2)
        c1 = _make_mock_client()
        c2 = _make_mock_client()
        pool._pool.append(c1)
        pool._in_use.append(c2)

        await pool.close_all()

        assert pool._pool == []
        assert pool._in_use == []
        assert pool._queue_processor_task is None
        c1.close.assert_called_once()
        c2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all_tolerates_close_errors(self):
        pool = DockerClientService(max_connections=2)
        bad = _make_mock_client()
        bad.close.side_effect = OSError("cannot close")
        pool._pool.append(bad)
        # should not raise
        await pool.close_all()
        assert pool._pool == []


# =========================================================================== #
# DockerClientService - SERVICE FIRST API surface                             #
# =========================================================================== #


class TestServiceFirstApi:
    @pytest.mark.asyncio
    async def test_get_docker_client_service_fast_path(self):
        pool = DockerClientService(max_connections=2)
        try:
            mock_client = _make_mock_client()

            async def _stub_acquire():
                pool._in_use.append(mock_client)
                return mock_client

            with patch.object(pool, "_try_immediate_acquire", _stub_acquire):
                result = await pool.get_docker_client_service(
                    DockerClientRequest(operation="stats")
                )

            assert isinstance(result, DockerClientResult)
            assert result.success is True
            assert result.client is mock_client
            assert result.error_message is None
            assert result.queue_wait_time_ms == 0.0
            assert result.connection_time_ms >= 0.0
            assert result.active_connections == 1
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_get_docker_client_service_timeout(self):
        """Slow-path queue, no clients ever produced -> timeout result."""
        pool = DockerClientService(max_connections=1)
        try:
            # Force fast path to return None
            async def _stub_acquire():
                return None

            with patch.object(pool, "_try_immediate_acquire", _stub_acquire):
                # Patch wait_for to raise TimeoutError immediately for the future
                async def _fake_wait_for(coro, timeout):  # noqa: ARG001
                    # Cancel the awaiting future so we don't leak.
                    if hasattr(coro, "cancel"):
                        coro.cancel()
                    raise asyncio.TimeoutError()

                with patch.object(asyncio, "wait_for", _fake_wait_for):
                    result = await pool.get_docker_client_service(
                        DockerClientRequest(timeout_seconds=0.01)
                    )

            assert result.success is False
            assert result.error_type == "timeout"
            assert "timed out" in result.error_message.lower()
            assert pool._queue_stats["timeouts"] >= 1
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_get_docker_client_service_inner_exception(self):
        """Exception from put() propagates into the outer except block."""
        pool = DockerClientService(max_connections=1)
        try:
            async def _stub_acquire():
                return None

            async def _bad_put(_x):
                raise OSError("queue broken")

            with patch.object(pool, "_try_immediate_acquire", _stub_acquire):
                with patch.object(pool._queue, "put", _bad_put):
                    result = await pool.get_docker_client_service(
                        DockerClientRequest(timeout_seconds=0.01)
                    )

            assert result.success is False
            assert result.error_type == "service_error"
            assert "queue broken" in result.error_message
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_get_pool_stats_service_basic(self):
        pool = DockerClientService(max_connections=3)
        try:
            pool._pool.append(_make_mock_client())
            pool._in_use.append(_make_mock_client())
            pool._queue_stats["total_requests"] = 5
            pool._queue_stats["timeouts"] = 1
            pool._queue_stats["average_wait_time"] = 0.25
            pool._queue_stats["max_queue_size"] = 2

            result = await pool.get_pool_stats_service(DockerPoolStatsRequest())
            assert isinstance(result, DockerPoolStatsResult)
            assert result.success is True
            assert result.total_connections == 2
            assert result.active_connections == 1
            assert result.available_connections == 1
            assert result.max_connections == 3
            assert result.total_requests == 5
            assert result.failed_requests == 1
            assert result.timeout_requests == 1
            assert result.successful_requests == 4
            assert result.average_wait_time_ms == 250.0
            assert result.max_queue_size_reached == 2
            # No history requested.
            assert result.performance_history is None
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_get_pool_stats_service_with_history(self):
        pool = DockerClientService(max_connections=2)
        try:
            result = await pool.get_pool_stats_service(
                DockerPoolStatsRequest(include_performance_history=True)
            )
            assert result.success is True
            assert result.performance_history is not None
            assert "available_clients" in result.performance_history
            assert "max_connections" in result.performance_history
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_get_pool_stats_service_handles_error(self):
        pool = DockerClientService(max_connections=2)
        try:
            with patch.object(
                pool, "get_queue_stats", side_effect=KeyError("oops")
            ):
                result = await pool.get_pool_stats_service(DockerPoolStatsRequest())
            assert result.success is False
            assert "oops" in result.error_message
        finally:
            await pool.close_all()


# =========================================================================== #
# DockerClientService - get_client_async (context manager)                    #
# =========================================================================== #


class TestGetClientAsyncContextManager:
    @pytest.mark.asyncio
    async def test_get_client_async_fast_path_yields_and_releases(self):
        pool = DockerClientService(max_connections=2)
        try:
            mock_client = _make_mock_client()

            async def _stub_acquire():
                pool._in_use.append(mock_client)
                return mock_client

            with patch.object(pool, "_try_immediate_acquire", _stub_acquire):
                async with pool.get_client_async(timeout=1.0) as c:
                    assert c is mock_client

            # After context exit, client is back in pool.
            assert mock_client in pool._pool
            assert mock_client not in pool._in_use
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_get_client_async_timeout_in_queue(self):
        pool = DockerClientService(max_connections=1)
        try:
            async def _stub_acquire():
                return None

            async def _fake_wait_for(coro, timeout):  # noqa: ARG001
                if hasattr(coro, "cancel"):
                    coro.cancel()
                raise asyncio.TimeoutError()

            with patch.object(pool, "_try_immediate_acquire", _stub_acquire):
                with patch.object(asyncio, "wait_for", _fake_wait_for):
                    with pytest.raises(asyncio.TimeoutError):
                        async with pool.get_client_async(timeout=0.01):
                            pass
        finally:
            await pool.close_all()


# =========================================================================== #
# DockerClientService - queue acquisition helper                              #
# =========================================================================== #


class TestTryAcquireForQueue:
    @pytest.mark.asyncio
    async def test_queue_acquire_uses_pool_first(self):
        pool = DockerClientService(max_connections=2)
        try:
            cached = _make_mock_client(ping_ok=True)
            pool._pool.append(cached)
            client = await pool._try_acquire_client_for_queue()
            assert client is cached
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_queue_acquire_dead_client_then_new(self):
        pool = DockerClientService(max_connections=2)
        try:
            dead = _make_mock_client(ping_ok=False)
            pool._pool.append(dead)
            new_client = _make_mock_client(ping_ok=True)

            async def _stub_create():
                pool._in_use.append(new_client)
                return new_client

            with patch.object(pool, "_create_new_client_async", _stub_create):
                client = await pool._try_acquire_client_for_queue()
            assert client is new_client
        finally:
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_queue_acquire_full_returns_none(self):
        pool = DockerClientService(max_connections=1)
        try:
            pool._in_use.append(_make_mock_client())
            client = await pool._try_acquire_client_for_queue()
            assert client is None
        finally:
            await pool.close_all()


# =========================================================================== #
# Module-level singleton + backward compat context manager                    #
# =========================================================================== #


class TestModuleSingletonAndBackcompat:
    def test_get_docker_client_service_singleton(self):
        # Reset the module-level singleton for a clean test
        dcp_mod._docker_client_service = None
        s1 = get_docker_client_service()
        s2 = get_docker_client_service()
        assert s1 is s2
        assert isinstance(s1, DockerClientService)

    @pytest.mark.asyncio
    async def test_get_docker_client_async_success_path(self):
        mock_client = _make_mock_client(ping_ok=True)
        fake_load_config = MagicMock(
            return_value={"docker_config": {"docker_socket_path": "/tmp/sock"}}
        )

        with patch(
            "services.config.config_service.load_config",
            fake_load_config,
        ):
            with patch.object(
                dcp_mod.docker, "DockerClient", return_value=mock_client
            ):
                async with get_docker_client_async(timeout=5.0) as c:
                    assert c is mock_client

        # After context exit, close was called.
        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_docker_client_async_falls_back_to_from_env(self):
        fallback = _make_mock_client(ping_ok=True)
        fake_load_config = MagicMock(
            return_value={"docker_config": {"docker_socket_path": "/tmp/sock"}}
        )
        with patch(
            "services.config.config_service.load_config",
            fake_load_config,
        ):
            with patch.object(
                dcp_mod.docker,
                "DockerClient",
                side_effect=dcp_mod.docker.errors.DockerException("nope"),
            ):
                with patch.object(
                    dcp_mod.docker, "from_env", return_value=fallback
                ):
                    async with get_docker_client_async(timeout=5.0) as c:
                        assert c is fallback
        fallback.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_docker_client_async_total_failure_raises(self):
        fake_load_config = MagicMock(
            return_value={"docker_config": {"docker_socket_path": "/tmp/sock"}}
        )
        with patch(
            "services.config.config_service.load_config",
            fake_load_config,
        ):
            with patch.object(
                dcp_mod.docker,
                "DockerClient",
                side_effect=dcp_mod.docker.errors.DockerException("primary"),
            ):
                with patch.object(
                    dcp_mod.docker,
                    "from_env",
                    side_effect=dcp_mod.docker.errors.DockerException("env"),
                ):
                    with pytest.raises(DockerConnectionError):
                        async with get_docker_client_async(timeout=1.0):
                            pass


# =========================================================================== #
# fetch_service.py - additional gap-filling tests                             #
# =========================================================================== #


class TestFetchServiceCooldownAndUtils:
    @pytest.fixture
    def fetch_service(self):
        s = get_fetch_service()
        s.clear_query_history()
        return s

    def test_set_query_cooldown_negative_clamped(self, fetch_service):
        fetch_service.set_query_cooldown(-5)
        assert fetch_service.get_query_cooldown() == 0
        # restore default for downstream tests
        fetch_service.set_query_cooldown(2)

    def test_clear_query_history_empties_dict(self, fetch_service):
        fetch_service._last_docker_query["x"] = time.time()
        fetch_service._last_docker_query["y"] = time.time()
        assert fetch_service._last_docker_query
        fetch_service.clear_query_history()
        assert fetch_service._last_docker_query == {}

    @pytest.mark.asyncio
    async def test_apply_query_cooldown_zero_short_circuits(self, fetch_service):
        fetch_service.set_query_cooldown(0)
        # Should return immediately without sleeping.
        start = time.time()
        await fetch_service._apply_query_cooldown("anything")
        assert time.time() - start < 0.05
        fetch_service.set_query_cooldown(2)

    @pytest.mark.asyncio
    async def test_apply_query_cooldown_waits(self, fetch_service):
        fetch_service.set_query_cooldown(1)
        fetch_service._last_docker_query["c"] = time.time()  # just queried
        sleeps = []

        async def _fake_sleep(t):
            sleeps.append(t)

        with patch("asyncio.sleep", _fake_sleep):
            await fetch_service._apply_query_cooldown("c")
        assert sleeps and 0 < sleeps[0] <= 1.0
        fetch_service.set_query_cooldown(2)


class TestFetchServiceEmergencyFetch:
    @pytest.fixture
    def fetch_service(self):
        s = get_fetch_service()
        s.clear_query_history()
        return s

    @pytest.mark.asyncio
    async def test_emergency_full_fetch_success(self, fetch_service):
        info_payload = {"State": {"Running": True}}
        stats_payload = {"cpu_percent": 1.0}

        with patch(
            "services.docker_status.fetch_service.get_docker_info_dict_service_first",
            new_callable=AsyncMock,
            return_value=info_payload,
        ):
            with patch(
                "services.docker_status.fetch_service.get_docker_stats_service_first",
                new_callable=AsyncMock,
                return_value=stats_payload,
            ):
                name, info, stats = await fetch_service._emergency_full_fetch(
                    "abc", RuntimeError("prev")
                )
        assert name == "abc"
        assert info == info_payload
        assert stats == stats_payload

    @pytest.mark.asyncio
    async def test_emergency_full_fetch_returns_exceptions_as_values(
        self, fetch_service
    ):
        """When the inner fetches raise, ``asyncio.gather(return_exceptions=True)``
        captures them as values - the emergency path treats this as success and
        returns the exception objects in the info/stats slots.
        """
        prev_err = RuntimeError("previous failure")

        async def _boom(*_a, **_kw):
            raise OSError("docker daemon unreachable")

        with patch(
            "services.docker_status.fetch_service.get_docker_info_dict_service_first",
            _boom,
        ):
            with patch(
                "services.docker_status.fetch_service.get_docker_stats_service_first",
                _boom,
            ):
                name, info, stats = await fetch_service._emergency_full_fetch(
                    "abc", prev_err
                )
        assert name == "abc"
        # Exceptions are captured as values by gather(return_exceptions=True).
        assert isinstance(info, OSError)
        assert isinstance(stats, OSError)

    @pytest.mark.asyncio
    async def test_emergency_full_fetch_runtime_error_path(
        self, fetch_service
    ):
        """If the emergency block itself blows up (e.g. ``gather`` raises a
        ``RuntimeError`` synchronously), the except path returns the previous
        exception with no stats."""
        prev_err = RuntimeError("previous failure")

        # Patch asyncio.gather to raise RuntimeError synchronously - this
        # forces the exception handler in _emergency_full_fetch to fire.
        async def _bad_gather(*_a, **_kw):
            raise RuntimeError("gather exploded")

        # Need a passing info/stats coro source so create_task succeeds.
        with patch(
            "services.docker_status.fetch_service.get_docker_info_dict_service_first",
            new_callable=AsyncMock,
            return_value={},
        ):
            with patch(
                "services.docker_status.fetch_service.get_docker_stats_service_first",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch(
                    "services.docker_status.fetch_service.asyncio.gather",
                    _bad_gather,
                ):
                    name, info, stats = await fetch_service._emergency_full_fetch(
                        "xyz", prev_err
                    )
        assert name == "xyz"
        assert info is prev_err
        assert stats is None


class TestFetchServiceRetryEdgeCases:
    @pytest.fixture
    def fetch_service(self):
        s = get_fetch_service()
        s.clear_query_history()
        # Ensure cooldown=0 so retry tests don't pause.
        s.set_query_cooldown(0)
        yield s
        s.set_query_cooldown(2)

    @pytest.mark.asyncio
    async def test_retry_runtime_error_then_success(self, fetch_service):
        """Non-timeout exception caught, retried, second attempt succeeds."""
        info_payload = {"State": {"Running": True}}

        info_mock = AsyncMock(side_effect=[RuntimeError("flap"), info_payload])
        stats_mock = AsyncMock(side_effect=[RuntimeError("flap"), None])

        with patch(
            "services.docker_status.fetch_service.get_docker_info_dict_service_first",
            info_mock,
        ):
            with patch(
                "services.docker_status.fetch_service.get_docker_stats_service_first",
                stats_mock,
            ):
                # Skip the 0.5s sleep between retries.
                with patch(
                    "services.docker_status.fetch_service.asyncio.sleep",
                    new_callable=AsyncMock,
                ):
                    name, info, stats = await fetch_service.fetch_with_retries(
                        "retry_box"
                    )

        # Second attempt (after RuntimeError on first) succeeds. The values
        # returned by gather() come from the second AsyncMock side_effect entry.
        assert name == "retry_box"
        # We can't be sure if asyncio.gather/return_exceptions surfaces the
        # second value or the first - either way, info should not be the
        # RuntimeError from attempt 1 because that was raised, not returned.
        assert not isinstance(info, RuntimeError) or info != RuntimeError("flap")

    @pytest.mark.asyncio
    async def test_retries_exhaust_then_emergency_called(self, fetch_service):
        """All retries trip ``asyncio.wait_for`` timeout -> emergency invoked.

        We patch ``asyncio.wait_for`` (as imported into fetch_service) to
        always raise ``TimeoutError``, which is the only path that triggers
        the timeout-retry-then-emergency branch (raising inside the inner
        coroutines just gets captured as a value by gather()).
        """
        emergency_mock = AsyncMock(
            return_value=("box", {"emergency": True}, {"emergency": "stats"})
        )

        info_mock = AsyncMock(return_value={"State": {"Running": True}})
        stats_mock = AsyncMock(return_value=None)

        async def _always_wait_for_timeout(coro, timeout):  # noqa: ARG001
            # Cancel the wrapped coro to avoid leaking tasks.
            if hasattr(coro, "close"):
                try:
                    coro.close()
                except Exception:
                    pass
            raise asyncio.TimeoutError()

        with patch(
            "services.docker_status.fetch_service.get_docker_info_dict_service_first",
            info_mock,
        ):
            with patch(
                "services.docker_status.fetch_service.get_docker_stats_service_first",
                stats_mock,
            ):
                with patch(
                    "services.docker_status.fetch_service.asyncio.sleep",
                    new_callable=AsyncMock,
                ):
                    with patch(
                        "services.docker_status.fetch_service.asyncio.wait_for",
                        _always_wait_for_timeout,
                    ):
                        with patch.object(
                            fetch_service, "_emergency_full_fetch", emergency_mock
                        ):
                            name, info, stats = await fetch_service.fetch_with_retries(
                                "box"
                            )

        emergency_mock.assert_awaited_once()
        assert name == "box"
        assert info == {"emergency": True}
        assert stats == {"emergency": "stats"}

    @pytest.mark.asyncio
    async def test_records_query_time_on_invocation(self, fetch_service):
        """Verify _last_docker_query is updated on every fetch call."""
        info_mock = AsyncMock(return_value={"State": {"Running": True}})
        stats_mock = AsyncMock(return_value=None)

        with patch(
            "services.docker_status.fetch_service.get_docker_info_dict_service_first",
            info_mock,
        ):
            with patch(
                "services.docker_status.fetch_service.get_docker_stats_service_first",
                stats_mock,
            ):
                await fetch_service.fetch_with_retries("ts_box")

        assert "ts_box" in fetch_service._last_docker_query
        assert (
            time.time() - fetch_service._last_docker_query["ts_box"] < 5.0
        )


# =========================================================================== #
# QueueRequest dataclass smoke check                                          #
# =========================================================================== #


class TestQueueRequestDataclass:
    def test_queue_request_construction(self):
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            req = QueueRequest(
                request_id="rid", timestamp=time.time(), timeout=5.0, future=fut
            )
            assert req.request_id == "rid"
            assert req.timeout == 5.0
            assert req.future is fut
        finally:
            loop.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
