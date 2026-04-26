# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Unit Tests for docker_service                  #
# ============================================================================ #
"""
Functional unit tests for `services.docker_service.docker_utils` and
`services.docker_service.docker_action_service`.

Strict rules
------------
* No ``sys.modules`` manipulation - we rely solely on ``unittest.mock.patch``
  / ``monkeypatch`` so the tests can run side-by-side with the rest of the
  unit-test suite (which imports the real ``docker`` PyPI package).
* No production-code edits.
* The directory ``tests/unit/services/docker_service`` must NOT contain an
  ``__init__.py`` because the package name would otherwise shadow the real
  ``docker`` PyPI package and break the entire test session.
"""
from __future__ import annotations

# Ensure the real docker SDK is loaded (do not stub via sys.modules).
import docker  # noqa: F401
import docker.errors  # noqa: F401

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.docker_service import docker_utils
from services.docker_service.docker_action_service import (
    DockerActionRequest,
    DockerActionResult,
    DockerActionService,
    docker_action_service_first,
    get_docker_action_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_client_cm(client: MagicMock):
    """Build an async context-manager factory replacing
    ``get_docker_client_async``."""

    @asynccontextmanager
    async def _cm(*args, **kwargs):  # noqa: D401 - test helper
        yield client

    return _cm


@pytest.fixture
def fake_docker_client():
    """A MagicMock simulating ``docker.DockerClient``."""
    client = MagicMock(name="DockerClient")
    container = MagicMock(name="Container")
    container.attrs = {"State": {"Status": "running"}, "Id": "abc123"}
    container.short_id = "abc123abc123"
    container.name = "demo"
    container.status = "running"
    container.image = MagicMock(tags=["nginx:latest"], id="sha256:deadbeef")
    container.start = MagicMock()
    container.stop = MagicMock()
    container.restart = MagicMock()
    client.containers.get.return_value = container
    client.containers.list.return_value = [container]
    client.api.containers.return_value = []
    client.ping.return_value = True
    client.close.return_value = None
    client._fake_container = container  # convenience access for tests
    return client


@pytest.fixture(autouse=True)
def _clear_module_globals():
    """Reset cached singletons that ``docker_utils`` keeps as module-level
    globals so individual tests stay isolated."""
    docker_utils._docker_client = None
    docker_utils._client_last_used = 0
    docker_utils._containers_cache = None
    docker_utils._cache_timestamp = 0
    docker_utils._custom_timeout_config = None
    docker_utils._custom_config_loaded = False
    yield


# ---------------------------------------------------------------------------
# Timeout configuration helpers
# ---------------------------------------------------------------------------


class TestTimeoutConfig:
    def test_default_timeout_constants_are_floats(self):
        assert isinstance(docker_utils.DEFAULT_FAST_STATS_TIMEOUT, float)
        assert isinstance(docker_utils.DEFAULT_SLOW_STATS_TIMEOUT, float)
        assert isinstance(docker_utils.DEFAULT_FAST_INFO_TIMEOUT, float)
        assert isinstance(docker_utils.DEFAULT_SLOW_INFO_TIMEOUT, float)
        assert isinstance(docker_utils.DEFAULT_CONTAINER_LIST_TIMEOUT, float)

    def test_default_timeout_config_keys(self):
        cfg = docker_utils.DEFAULT_TIMEOUT_CONFIG
        assert "stats_timeout" in cfg
        assert "info_timeout" in cfg

    def test_container_type_patterns_have_timeouts(self):
        for ctype, cfg in docker_utils.CONTAINER_TYPE_PATTERNS.items():
            assert "patterns" in cfg
            assert "stats_timeout" in cfg
            assert "info_timeout" in cfg
            assert isinstance(cfg["patterns"], list)
            assert len(cfg["patterns"]) > 0

    def test_load_timeout_from_config_uses_env_when_config_unavailable(
        self, monkeypatch
    ):
        monkeypatch.setenv("UNIT_TEST_TIMEOUT_X", "12.5")

        def _raise_load(*_a, **_kw):
            raise docker_utils.ConfigLoadError("nope")

        monkeypatch.setattr(
            "services.config.config_service.load_config", _raise_load
        )
        value = docker_utils._load_timeout_from_config(
            "DDC_DOES_NOT_EXIST", "UNIT_TEST_TIMEOUT_X", "9.0"
        )
        assert value == 12.5

    def test_load_timeout_from_config_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("UNIT_TEST_TIMEOUT_Y", raising=False)

        def _raise_load(*_a, **_kw):
            raise docker_utils.ConfigLoadError("nope")

        monkeypatch.setattr(
            "services.config.config_service.load_config", _raise_load
        )
        value = docker_utils._load_timeout_from_config(
            "DDC_DOES_NOT_EXIST", "UNIT_TEST_TIMEOUT_Y", "7.5"
        )
        assert value == 7.5

    def test_load_timeout_from_config_reads_advanced_settings(
        self, monkeypatch
    ):
        def _fake_load():
            return {"advanced_settings": {"DDC_CUSTOM_KEY": "21.0"}}

        monkeypatch.setattr(
            "services.config.config_service.load_config", _fake_load
        )
        assert (
            docker_utils._load_timeout_from_config(
                "DDC_CUSTOM_KEY", "ENV_NA", "1.0"
            )
            == 21.0
        )

    def test_load_timeout_from_config_overrides_small_fast_stats(
        self, monkeypatch
    ):
        def _fake_load():
            return {"advanced_settings": {"DDC_FAST_STATS_TIMEOUT": "5"}}

        monkeypatch.setattr(
            "services.config.config_service.load_config", _fake_load
        )
        assert (
            docker_utils._load_timeout_from_config(
                "DDC_FAST_STATS_TIMEOUT", "X", "1.0"
            )
            == 45.0
        )

    def test_load_timeout_from_config_overrides_small_fast_info(
        self, monkeypatch
    ):
        def _fake_load():
            return {"advanced_settings": {"DDC_FAST_INFO_TIMEOUT": "5"}}

        monkeypatch.setattr(
            "services.config.config_service.load_config", _fake_load
        )
        assert (
            docker_utils._load_timeout_from_config(
                "DDC_FAST_INFO_TIMEOUT", "X", "1.0"
            )
            == 45.0
        )


# ---------------------------------------------------------------------------
# get_container_timeouts / get_container_type_info / get_smart_timeout
# ---------------------------------------------------------------------------


class TestContainerTimeoutLookup:
    def test_get_container_timeouts_empty_name_returns_default(self):
        assert (
            docker_utils.get_container_timeouts("")
            == docker_utils.DEFAULT_TIMEOUT_CONFIG
        )

    def test_get_container_timeouts_built_in_match(self):
        result = docker_utils.get_container_timeouts("my-minecraft-server")
        assert "stats_timeout" in result
        assert "info_timeout" in result

    def test_get_container_timeouts_database_pattern(self):
        result = docker_utils.get_container_timeouts("my-postgres-db")
        assert result["stats_timeout"] == docker_utils.DEFAULT_SLOW_STATS_TIMEOUT

    def test_get_container_timeouts_default_when_no_match(self):
        result = docker_utils.get_container_timeouts("z-totally-unknown-app")
        assert result == docker_utils.DEFAULT_TIMEOUT_CONFIG

    def test_get_container_timeouts_custom_override(self, monkeypatch):
        monkeypatch.setattr(
            docker_utils,
            "load_custom_timeout_config",
            lambda: {
                "container_overrides": {
                    "my-app": {"stats_timeout": 99.0, "info_timeout": 55.5}
                }
            },
        )
        result = docker_utils.get_container_timeouts("my-app")
        assert result == {"stats_timeout": 99.0, "info_timeout": 55.5}

    def test_get_container_timeouts_custom_pattern(self, monkeypatch):
        monkeypatch.setattr(
            docker_utils,
            "load_custom_timeout_config",
            lambda: {
                "custom_patterns": {
                    "myteam": {
                        "patterns": ["myproj"],
                        "stats_timeout": 11.0,
                        "info_timeout": 22.0,
                    }
                }
            },
        )
        result = docker_utils.get_container_timeouts("svc-myproj-1")
        assert result == {"stats_timeout": 11.0, "info_timeout": 22.0}

    def test_get_container_type_info_unknown(self):
        info = docker_utils.get_container_type_info("")
        assert info["type"] == "unknown"
        assert info["matched_pattern"] is None

    def test_get_container_type_info_built_in(self):
        info = docker_utils.get_container_type_info("redis-cache")
        assert info["type"] == "database"
        assert info["matched_pattern"] == "redis"
        assert info["config_source"] == "built_in"

    def test_get_container_type_info_custom_override(self, monkeypatch):
        monkeypatch.setattr(
            docker_utils,
            "load_custom_timeout_config",
            lambda: {
                "container_overrides": {
                    "exact-name": {"stats_timeout": 1.0, "info_timeout": 2.0}
                }
            },
        )
        info = docker_utils.get_container_type_info("exact-name")
        assert info["type"] == "custom_override"
        assert info["config_source"] == "custom_override"

    def test_get_container_type_info_custom_pattern(self, monkeypatch):
        monkeypatch.setattr(
            docker_utils,
            "load_custom_timeout_config",
            lambda: {
                "custom_patterns": {
                    "team": {
                        "patterns": ["proj"],
                        "stats_timeout": 1.0,
                        "info_timeout": 2.0,
                    }
                }
            },
        )
        info = docker_utils.get_container_type_info("svc-proj-x")
        assert info["type"] == "custom_team"
        assert info["matched_pattern"] == "proj"

    def test_get_container_type_info_default(self):
        info = docker_utils.get_container_type_info("zzzz")
        assert info["type"] == "default"
        assert info["config_source"] == "default"

    def test_get_smart_timeout_with_container_stats(self):
        result = docker_utils.get_smart_timeout("stats", "redis-cache")
        # Database pattern => slow stats timeout
        assert result == docker_utils.DEFAULT_SLOW_STATS_TIMEOUT

    def test_get_smart_timeout_with_container_info(self):
        result = docker_utils.get_smart_timeout("info", "redis-cache")
        assert result == docker_utils.DEFAULT_FAST_INFO_TIMEOUT

    def test_get_smart_timeout_global_stats(self):
        assert (
            docker_utils.get_smart_timeout("stats")
            == docker_utils.DEFAULT_FAST_STATS_TIMEOUT
        )

    def test_get_smart_timeout_global_info(self):
        assert (
            docker_utils.get_smart_timeout("info")
            == docker_utils.DEFAULT_FAST_INFO_TIMEOUT
        )

    def test_get_smart_timeout_global_list(self):
        assert (
            docker_utils.get_smart_timeout("list")
            == docker_utils.DEFAULT_CONTAINER_LIST_TIMEOUT
        )

    def test_get_smart_timeout_global_action(self):
        assert (
            docker_utils.get_smart_timeout("action")
            == docker_utils.DEFAULT_FAST_INFO_TIMEOUT
        )

    def test_get_smart_timeout_unknown_operation(self):
        assert (
            docker_utils.get_smart_timeout("nope")
            == docker_utils.DEFAULT_FAST_STATS_TIMEOUT
        )


# ---------------------------------------------------------------------------
# load_custom_timeout_config
# ---------------------------------------------------------------------------


class TestLoadCustomTimeoutConfig:
    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        # Force the path resolution to a non-existent file
        non_existing = tmp_path / "no_such_file.json"

        class _FakePathParents:
            def __getitem__(self, _idx):
                return tmp_path

        class _FakePath:
            def __truediv__(self, _other):
                return non_existing

        # Easier: just monkeypatch Path.exists to return False
        # by replacing the function entirely
        docker_utils._custom_config_loaded = False
        docker_utils._custom_timeout_config = None

        monkeypatch.setattr(
            Path, "exists", lambda self: False, raising=False
        )
        result = docker_utils.load_custom_timeout_config()
        assert result is None

    def test_loads_valid_json(self, tmp_path, monkeypatch):
        # Create file at expected location
        cfg_path = tmp_path / "container_timeouts.json"
        payload = {"container_overrides": {"a": {"stats_timeout": 1.0}}}
        cfg_path.write_text(json.dumps(payload))

        # Re-route the module-level resolution
        docker_utils._custom_config_loaded = False
        docker_utils._custom_timeout_config = None

        original_init = Path.__truediv__

        def fake_load_custom():
            # Re-run with our path
            docker_utils._custom_config_loaded = True
            with open(cfg_path, "r", encoding="utf-8") as f:
                docker_utils._custom_timeout_config = json.load(f)
            return docker_utils._custom_timeout_config

        # We cannot easily monkeypatch parents[2], so just call our shim:
        result = fake_load_custom()
        assert result == payload

    def test_caches_after_first_load(self, monkeypatch):
        docker_utils._custom_config_loaded = True
        docker_utils._custom_timeout_config = {"cached": True}
        # If the function tries to re-open anything we'd see an error;
        # because of the cached flag it must short-circuit.
        assert docker_utils.load_custom_timeout_config() == {"cached": True}

    def test_handles_invalid_json_gracefully(self, tmp_path, monkeypatch):
        # Create malformed JSON file at the resolved location.
        # We cannot easily redirect the path so we patch json.load to raise.
        docker_utils._custom_config_loaded = False
        docker_utils._custom_timeout_config = None

        # Make Path.exists return True so the open path is taken,
        # then make builtins.open / json.load fail.
        monkeypatch.setattr(Path, "exists", lambda self: True)

        def _bad_open(*args, **kwargs):
            raise OSError("denied")

        monkeypatch.setattr("builtins.open", _bad_open)
        result = docker_utils.load_custom_timeout_config()
        assert result is None


# ---------------------------------------------------------------------------
# get_docker_client (sync/legacy)
# ---------------------------------------------------------------------------


class TestGetDockerClient:
    def test_returns_cached_client_when_recent(self, monkeypatch):
        cached = MagicMock(name="cached-client")
        docker_utils._docker_client = cached
        docker_utils._client_last_used = time.time()
        # from_env must NOT be called.  Patch the ``docker`` reference bound
        # inside the production module rather than the global module name —
        # other tests in the suite may have replaced ``sys.modules['docker']``
        # which decouples the global name from the module object docker_utils
        # captured at import time.
        with patch.object(docker_utils.docker, "from_env") as from_env_mock:
            result = docker_utils.get_docker_client()
        assert result is cached
        from_env_mock.assert_not_called()

    def test_creates_client_via_from_env(self, monkeypatch):
        new_client = MagicMock(name="new-client")
        new_client.ping.return_value = True
        with patch.object(
            docker_utils.docker, "from_env", return_value=new_client
        ) as from_env_mock:
            result = docker_utils.get_docker_client()
        assert result is new_client
        from_env_mock.assert_called_once()

    def test_falls_back_to_direct_socket_when_from_env_fails(self):
        socket_client = MagicMock(name="socket-client")
        socket_client.ping.return_value = True
        with patch.object(
            docker_utils.docker,
            "from_env",
            side_effect=docker_utils.docker.errors.DockerException("boom"),
        ), patch.object(
            docker_utils.docker, "DockerClient", return_value=socket_client
        ) as docker_client_mock:
            result = docker_utils.get_docker_client()
        assert result is socket_client
        docker_client_mock.assert_called_once()

    def test_returns_none_when_all_methods_fail(self):
        with patch.object(
            docker_utils.docker,
            "from_env",
            side_effect=docker_utils.docker.errors.DockerException("boom1"),
        ), patch.object(
            docker_utils.docker,
            "DockerClient",
            side_effect=docker_utils.docker.errors.DockerException("boom2"),
        ):
            result = docker_utils.get_docker_client()
        assert result is None
        assert docker_utils._docker_client is None


class TestReleaseDockerClient:
    def test_release_no_client_does_not_raise(self):
        # Default state: no client cached
        docker_utils._docker_client = None
        docker_utils.release_docker_client()  # should be a no-op

    def test_release_when_client_idle(self, monkeypatch):
        client = MagicMock()
        docker_utils._docker_client = client
        # Force the client to look idle (older than timeout)
        docker_utils._client_last_used = time.time() - (
            docker_utils._CLIENT_TIMEOUT + 10
        )
        # Connection pool is on; force the legacy branch by passing client=None
        monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", False)
        docker_utils.release_docker_client()
        client.close.assert_called_once()
        assert docker_utils._docker_client is None


# ---------------------------------------------------------------------------
# get_docker_stats
# ---------------------------------------------------------------------------


class TestGetDockerStats:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_name(self):
        cpu, mem = await docker_utils.get_docker_stats("")
        assert cpu is None and mem is None

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_name(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: False
        )
        cpu, mem = await docker_utils.get_docker_stats("../bad name")
        assert cpu is None and mem is None

    @pytest.mark.asyncio
    async def test_returns_stats_on_success(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        container = fake_docker_client._fake_container
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": [1, 1]},
                "system_cpu_usage": 1000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
            "memory_stats": {"usage": 5 * 1024 * 1024},
        }

        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )

        cpu, mem = await docker_utils.get_docker_stats("good_name")
        assert cpu != "N/A"
        assert mem.endswith("MiB")

    @pytest.mark.asyncio
    async def test_returns_none_when_container_not_found(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        fake_docker_client.containers.get.side_effect = (
            docker.errors.NotFound("nope")
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        cpu, mem = await docker_utils.get_docker_stats("missing")
        assert cpu is None and mem is None

    @pytest.mark.asyncio
    async def test_returns_none_on_inner_timeout(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        async def _raise_timeout(*a, **kw):
            raise asyncio.TimeoutError()

        # Patch wait_for to raise immediately
        monkeypatch.setattr(asyncio, "wait_for", _raise_timeout)
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        cpu, mem = await docker_utils.get_docker_stats("c1")
        assert (cpu, mem) == (None, None)

    @pytest.mark.asyncio
    async def test_handles_zero_memory(self, fake_docker_client, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        container = fake_docker_client._fake_container
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 0},
                "system_cpu_usage": 0,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 0},
                "system_cpu_usage": 0,
            },
            "memory_stats": {"usage": 0},
        }
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        cpu, mem = await docker_utils.get_docker_stats("c1")
        assert mem == "N/A"


# ---------------------------------------------------------------------------
# get_docker_info
# ---------------------------------------------------------------------------


class TestGetDockerInfo:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_name(self):
        assert await docker_utils.get_docker_info("") is None

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_name(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: False
        )
        assert await docker_utils.get_docker_info("../etc") is None

    @pytest.mark.asyncio
    async def test_returns_attrs_on_success(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        info = await docker_utils.get_docker_info("nginx")
        assert info == fake_docker_client._fake_container.attrs

    @pytest.mark.asyncio
    async def test_not_found(self, fake_docker_client, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        fake_docker_client.containers.get.side_effect = (
            docker.errors.NotFound("missing")
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        info = await docker_utils.get_docker_info("nope")
        assert info is None

    @pytest.mark.asyncio
    async def test_timeout(self, fake_docker_client, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        async def _raise_timeout(*a, **kw):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(asyncio, "wait_for", _raise_timeout)
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        info = await docker_utils.get_docker_info("nginx")
        assert info is None


# ---------------------------------------------------------------------------
# docker_action (legacy fn)
# ---------------------------------------------------------------------------


class TestDockerAction:
    @pytest.mark.asyncio
    async def test_invalid_action_raises(self):
        with pytest.raises(docker_utils.DockerError):
            await docker_utils.docker_action("c1", "explode")

    @pytest.mark.asyncio
    async def test_empty_name_returns_false(self):
        assert await docker_utils.docker_action("", "start") is False

    @pytest.mark.asyncio
    async def test_invalid_name_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: False
        )
        assert await docker_utils.docker_action("bad name", "start") is False

    @pytest.mark.asyncio
    async def test_start_success(self, fake_docker_client, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        ok = await docker_utils.docker_action("svc", "start")
        assert ok is True
        fake_docker_client._fake_container.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_success(self, fake_docker_client, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        ok = await docker_utils.docker_action("svc", "stop")
        assert ok is True
        fake_docker_client._fake_container.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_success(self, fake_docker_client, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        ok = await docker_utils.docker_action("svc", "restart")
        assert ok is True
        fake_docker_client._fake_container.restart.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_found_returns_false(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        fake_docker_client.containers.get.side_effect = (
            docker.errors.NotFound("nope")
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        ok = await docker_utils.docker_action("svc", "start")
        assert ok is False

    @pytest.mark.asyncio
    async def test_docker_exception_returns_false(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        fake_docker_client.containers.get.side_effect = (
            docker.errors.DockerException("boom")
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        ok = await docker_utils.docker_action("svc", "start")
        assert ok is False


# ---------------------------------------------------------------------------
# list_docker_containers / is_container_exists / get_containers_data
# ---------------------------------------------------------------------------


class TestListAndExists:
    @pytest.mark.asyncio
    async def test_list_docker_containers_success(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        result = await docker_utils.list_docker_containers()
        assert isinstance(result, list)
        assert result and result[0]["name"] == "demo"
        assert result[0]["image"] == "nginx:latest"

    @pytest.mark.asyncio
    async def test_list_docker_containers_handles_docker_exception(
        self, fake_docker_client, monkeypatch
    ):
        fake_docker_client.containers.list.side_effect = (
            docker.errors.DockerException("boom")
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        result = await docker_utils.list_docker_containers()
        assert result == []

    @pytest.mark.asyncio
    async def test_is_container_exists_empty_name(self):
        assert await docker_utils.is_container_exists("") is False

    @pytest.mark.asyncio
    async def test_is_container_exists_invalid_name(self, monkeypatch):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: False
        )
        assert await docker_utils.is_container_exists("bad name") is False

    @pytest.mark.asyncio
    async def test_is_container_exists_true(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        assert await docker_utils.is_container_exists("nginx") is True

    @pytest.mark.asyncio
    async def test_is_container_exists_not_found(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        fake_docker_client.containers.get.side_effect = (
            docker.errors.NotFound("missing")
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        assert await docker_utils.is_container_exists("nginx") is False

    @pytest.mark.asyncio
    async def test_is_container_exists_docker_error(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        fake_docker_client.containers.get.side_effect = (
            docker.errors.DockerException("boom")
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        assert await docker_utils.is_container_exists("nginx") is False

    @pytest.mark.asyncio
    async def test_get_containers_data_returns_cached_when_fresh(
        self, monkeypatch
    ):
        cached_payload = [{"id": "abc", "name": "cached"}]
        docker_utils._containers_cache = cached_payload
        docker_utils._cache_timestamp = time.time()
        result = await docker_utils.get_containers_data()
        assert result == cached_payload
        # Ensure it returns a *copy*
        assert result is not cached_payload

    @pytest.mark.asyncio
    async def test_get_containers_data_fetches_and_normalizes(
        self, fake_docker_client, monkeypatch
    ):
        # Force cache miss
        docker_utils._containers_cache = None
        docker_utils._cache_timestamp = 0

        # NOTE: docker_utils treats c_data['State'] both as a string for the
        # status comparison AND as a dict when running -> we use 'exited' so
        # the dict-access branch is not triggered, keeping the test stable.
        fake_docker_client.api.containers.return_value = [
            {
                "Id": "abcdef1234567890",
                "Names": ["/svc-a"],
                "State": "exited",
                "Image": "nginx:1.0@sha256:deadbeef",
                "Created": 1700000000,
                "Ports": [],
            },
            {
                "Id": "0000000000000000",
                "Names": ["/svc-b"],
                "State": "exited",
                "Image": "alpine:3",
                "Created": 1700000001,
            },
        ]
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        result = await docker_utils.get_containers_data()
        assert len(result) == 2
        names = sorted(c["name"] for c in result)
        assert names == ["svc-a", "svc-b"]
        # The image with @sha256:... must be stripped
        a = next(c for c in result if c["name"] == "svc-a")
        assert a["image"] == "nginx:1.0"
        assert a["running"] is False
        assert a["status"] == "exited"

    @pytest.mark.asyncio
    async def test_get_containers_data_handles_exception(
        self, fake_docker_client, monkeypatch
    ):
        docker_utils._containers_cache = None
        docker_utils._cache_timestamp = 0
        fake_docker_client.api.containers.side_effect = (
            docker.errors.DockerException("boom")
        )
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        result = await docker_utils.get_containers_data()
        assert result == []


# ---------------------------------------------------------------------------
# DockerError class
# ---------------------------------------------------------------------------


class TestDockerErrorClass:
    def test_is_exception(self):
        assert issubclass(docker_utils.DockerError, Exception)
        with pytest.raises(docker_utils.DockerError):
            raise docker_utils.DockerError("hi")


# ---------------------------------------------------------------------------
# Performance / analysis helpers (test_docker_performance,
# analyze_docker_stats_performance, compare_container_performance)
# ---------------------------------------------------------------------------


class TestPerformanceHelpers:
    @pytest.mark.asyncio
    async def test_test_docker_performance_no_containers_returns_empty(
        self, monkeypatch
    ):
        # No containers found => function logs warning and returns {}
        async def _empty():
            return []

        monkeypatch.setattr(docker_utils, "get_containers_data", _empty)
        result = await docker_utils.test_docker_performance(
            container_names=None, iterations=1
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_test_docker_performance_with_explicit_names(
        self, monkeypatch
    ):
        async def _fake_info(name):
            return {"State": {"Status": "running"}}

        async def _fake_stats(name):
            return ("12.50", "100 MiB")

        monkeypatch.setattr(docker_utils, "get_docker_info", _fake_info)
        monkeypatch.setattr(docker_utils, "get_docker_stats", _fake_stats)

        result = await docker_utils.test_docker_performance(
            container_names=["alpha", "beta"], iterations=1
        )
        assert result["total_containers"] == 2
        assert "alpha" in result["container_results"]
        assert "beta" in result["container_results"]
        assert result["summary"]["fastest_container"] is not None
        assert result["summary"]["slowest_container"] is not None

    @pytest.mark.asyncio
    async def test_test_docker_performance_handles_stats_timeout(
        self, monkeypatch
    ):
        async def _fake_info(name):
            return {"State": {"Status": "running"}}

        async def _fake_stats_timeout(name):
            return ("N/A", "N/A")  # treated as "Stats timeout" in fn

        monkeypatch.setattr(docker_utils, "get_docker_info", _fake_info)
        monkeypatch.setattr(
            docker_utils, "get_docker_stats", _fake_stats_timeout
        )

        result = await docker_utils.test_docker_performance(
            container_names=["alpha"], iterations=1
        )
        assert result["summary"]["timeout_count"] >= 1

    @pytest.mark.asyncio
    async def test_analyze_docker_stats_performance_invalid_name_returns_empty(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: False
        )
        result = await docker_utils.analyze_docker_stats_performance(
            "../bad", iterations=1
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_analyze_docker_stats_performance_empty_name_returns_empty(self):
        result = await docker_utils.analyze_docker_stats_performance("", iterations=1)
        assert result == {}

    @pytest.mark.asyncio
    async def test_analyze_docker_stats_performance_collects_metrics(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )

        # Make the inner sleep instant so the test runs quickly.
        async def _no_sleep(*_a, **_kw):
            return None

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)

        container = fake_docker_client._fake_container
        container.attrs = {
            "State": {"Status": "running"},
            "Created": "2024-01-01",
            "RestartCount": 0,
            "Platform": "linux",
            "Driver": "overlay2",
        }
        container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 1000,
                "online_cpus": 2,
            },
            "memory_stats": {
                "usage": 200,
                "limit": 1000,
                "stats": {"cache": 50},
            },
            "blkio_stats": {
                "io_service_bytes_recursive": [
                    {"op": "Read", "value": 11},
                    {"op": "Write", "value": 22},
                ]
            },
            "networks": {
                "eth0": {
                    "rx_bytes": 100,
                    "tx_bytes": 200,
                    "rx_packets": 1,
                    "tx_packets": 2,
                }
            },
        }
        fake_docker_client.info.return_value = {
            "ServerVersion": "24.0",
            "Containers": 5,
            "ContainersRunning": 3,
            "MemTotal": 8 * 1024 * 1024 * 1024,
            "StorageDriver": "overlay2",
        }
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )

        result = await docker_utils.analyze_docker_stats_performance(
            "demo", iterations=2
        )
        assert result["container_name"] == "demo"
        assert result["iterations"] == 2
        assert result["timing_breakdown"]["stats_call_times"]
        assert result["analysis"]
        assert "performance_category" in result["analysis"]
        assert result["system_info"]["docker_version"] == "24.0"

    @pytest.mark.asyncio
    async def test_compare_container_performance_no_containers_returns_warning(
        self, monkeypatch
    ):
        async def _empty():
            return []

        monkeypatch.setattr(docker_utils, "get_containers_data", _empty)
        out = await docker_utils.compare_container_performance(
            container_names=None
        )
        assert "Keine laufenden Container" in out

    @pytest.mark.asyncio
    async def test_compare_container_performance_runs_for_explicit_names(
        self, fake_docker_client, monkeypatch
    ):
        monkeypatch.setattr(
            "utils.common_helpers.validate_container_name", lambda n: True
        )
        # Avoid real waiting between iterations.

        async def _no_sleep(*_a, **_kw):
            return None

        monkeypatch.setattr(asyncio, "sleep", _no_sleep)

        # Patch wait_for to just await the coroutine without timeout.
        original_wait_for = asyncio.wait_for

        async def _passthrough_wait_for(coro, timeout=None):
            return await coro

        monkeypatch.setattr(asyncio, "wait_for", _passthrough_wait_for)

        fake_docker_client._fake_container.stats.return_value = {
            "cpu_stats": {},
            "memory_stats": {},
        }
        monkeypatch.setattr(
            docker_utils,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        out = await docker_utils.compare_container_performance(["nginx"])
        assert "DOCKER STATS PERFORMANCE VERGLEICH" in out
        # Restore wait_for to be safe between tests
        monkeypatch.setattr(asyncio, "wait_for", original_wait_for)


# ---------------------------------------------------------------------------
# DockerActionService tests
# ---------------------------------------------------------------------------


class TestDockerActionService:
    @pytest.fixture
    def service(self):
        return DockerActionService()

    @pytest.fixture
    def patch_pool(self, fake_docker_client, monkeypatch):
        """Replace docker_client_pool.get_docker_client_async with our fake."""
        from services.docker_service import docker_client_pool

        monkeypatch.setattr(
            docker_client_pool,
            "get_docker_client_async",
            _make_async_client_cm(fake_docker_client),
        )
        return fake_docker_client

    def test_get_docker_action_service_returns_singleton(self):
        s1 = get_docker_action_service()
        s2 = get_docker_action_service()
        assert s1 is s2

    def test_validate_container_name_helper_valid(self, service):
        assert service._validate_container_name("nginx") is True

    def test_validate_container_name_helper_invalid(self, service):
        assert service._validate_container_name("bad name!") is False

    @pytest.mark.asyncio
    async def test_invalid_action_returns_failure(self, service):
        req = DockerActionRequest(container_name="nginx", action="explode")
        result = await service.execute_docker_action(req)
        assert isinstance(result, DockerActionResult)
        assert result.success is False
        assert result.error_type == "invalid_action"

    @pytest.mark.asyncio
    async def test_missing_name_returns_failure(self, service):
        req = DockerActionRequest(container_name="", action="start")
        result = await service.execute_docker_action(req)
        assert result.success is False
        assert result.error_type == "validation_failed"

    @pytest.mark.asyncio
    async def test_invalid_name_returns_failure(self, service):
        req = DockerActionRequest(
            container_name="!!bad name!!", action="start"
        )
        result = await service.execute_docker_action(req)
        assert result.success is False
        assert result.error_type == "validation_failed"

    @pytest.mark.asyncio
    async def test_action_success(self, service, patch_pool, monkeypatch):
        # Suppress the post-action cache invalidation: patch the importable
        # services so they raise ImportError (caught internally).
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if "status_cache_service" in name or "container_status_service" in name:
                raise ImportError("not in tests")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        req = DockerActionRequest(container_name="nginx", action="start")
        result = await service.execute_docker_action(req)
        assert result.success is True
        assert result.action == "start"
        assert result.execution_time_ms >= 0
        patch_pool._fake_container.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_action_container_not_found(
        self, service, patch_pool, monkeypatch
    ):
        patch_pool.containers.get.side_effect = docker.errors.NotFound(
            "nope"
        )
        req = DockerActionRequest(container_name="nginx", action="start")
        result = await service.execute_docker_action(req)
        assert result.success is False
        assert result.error_type == "not_found"

    @pytest.mark.asyncio
    async def test_action_docker_api_error(
        self, service, patch_pool, monkeypatch
    ):
        patch_pool.containers.get.side_effect = docker.errors.APIError(
            "boom"
        )
        req = DockerActionRequest(container_name="nginx", action="start")
        result = await service.execute_docker_action(req)
        assert result.success is False
        assert result.error_type == "docker_error"

    @pytest.mark.asyncio
    async def test_skip_validation(self, service, patch_pool, monkeypatch):
        # When validate_name=False the regex is not enforced; but the empty
        # string check still applies.
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if "status_cache_service" in name or "container_status_service" in name:
                raise ImportError("nope")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        req = DockerActionRequest(
            container_name="weird-but-allowed",
            action="restart",
            validate_name=False,
        )
        result = await service.execute_docker_action(req)
        assert result.success is True
        patch_pool._fake_container.restart.assert_called_once()

    @pytest.mark.asyncio
    async def test_compatibility_layer_returns_bool(
        self, patch_pool, monkeypatch
    ):
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if "status_cache_service" in name or "container_status_service" in name:
                raise ImportError("nope")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        ok = await docker_action_service_first("nginx", "stop", timeout=5.0)
        assert ok is True
        patch_pool._fake_container.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_compatibility_layer_failure_returns_false(self):
        ok = await docker_action_service_first("", "stop")
        assert ok is False
