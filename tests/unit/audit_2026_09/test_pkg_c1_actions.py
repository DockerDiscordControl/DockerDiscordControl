# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
# -*- coding: utf-8 -*-
"""
Audit 2026-09, package C1 - container actions.

Regression tests for:
    C1-8  restart()/stop() honour the container's own StopTimeout (docker-py's restart()
          would force 10s); a requests ReadTimeout from stop() is a clean failure
"""

import builtins
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
import requests

from services.docker_service import docker_client_pool, docker_utils
from services.docker_service.docker_action_service import (
    DockerActionRequest,
    DockerActionService,
    get_stop_timeout_kwargs,
)


def _container(stop_timeout=None):
    container = MagicMock(name="Container")
    config = {"Image": "img:1"}
    if stop_timeout is not None:
        config["StopTimeout"] = stop_timeout
    container.attrs = {"Config": config}
    return container


def _client_cm_factory(container):
    client = MagicMock(name="DockerClient")
    client.containers.get.return_value = container

    @asynccontextmanager
    async def _cm(*_a, **_kw):
        yield client

    return lambda *a, **kw: _cm()


@pytest.fixture
def no_cache_invalidation(monkeypatch):
    """Skip DockerActionService's post-action cache invalidation (ImportError is caught)."""
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if "status_cache_service" in name or "container_status_service" in name:
            raise ImportError("not in tests")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)


class TestStopTimeoutKwargs:

    @pytest.mark.parametrize("attrs,expected", [
        ({"Config": {"StopTimeout": 120}}, {"timeout": 120}),
        ({"Config": {"StopTimeout": 0}}, {"timeout": 0}),
        ({"Config": {}}, {}),
        ({"Config": None}, {}),
        ({}, {}),
        ({"Config": {"StopTimeout": -1}}, {}),
        ({"Config": {"StopTimeout": True}}, {}),
        ({"Config": {"StopTimeout": "60"}}, {}),
    ])
    def test_kwargs_from_container_config(self, attrs, expected):
        container = MagicMock()
        container.attrs = attrs
        assert get_stop_timeout_kwargs(container) == expected

    def test_unusable_attrs_fall_back_to_docker_py_defaults(self):
        assert get_stop_timeout_kwargs(MagicMock()) == {}


class TestDockerActionServiceStopTimeout:

    @pytest.mark.parametrize("action", ["restart", "stop"])
    async def test_uses_container_stop_timeout(self, action, monkeypatch, no_cache_invalidation):
        container = _container(stop_timeout=120)
        monkeypatch.setattr(docker_client_pool, "get_docker_client_async", _client_cm_factory(container))

        result = await DockerActionService().execute_docker_action(
            DockerActionRequest(container_name="Icarus", action=action))

        assert result.success is True
        getattr(container, action).assert_called_once_with(timeout=120)

    async def test_restart_without_stop_timeout_keeps_default(self, monkeypatch, no_cache_invalidation):
        container = _container()
        monkeypatch.setattr(docker_client_pool, "get_docker_client_async", _client_cm_factory(container))

        result = await DockerActionService().execute_docker_action(
            DockerActionRequest(container_name="Icarus", action="restart"))

        assert result.success is True
        container.restart.assert_called_once_with()

    async def test_stop_read_timeout_returns_clean_failure(self, monkeypatch, no_cache_invalidation):
        container = _container(stop_timeout=300)
        container.stop.side_effect = requests.exceptions.ReadTimeout("Read timed out")
        monkeypatch.setattr(docker_client_pool, "get_docker_client_async", _client_cm_factory(container))

        result = await DockerActionService().execute_docker_action(
            DockerActionRequest(container_name="Icarus", action="stop"))

        assert result.success is False
        assert result.error_type == "docker_error"
        assert "Read timed out" in result.error_message


class TestDockerUtilsActionStopTimeout:

    @pytest.fixture(autouse=True)
    def _valid_names(self, monkeypatch):
        monkeypatch.setattr("utils.common_helpers.validate_container_name", lambda n: True)

    @pytest.mark.parametrize("action", ["restart", "stop"])
    async def test_uses_container_stop_timeout(self, action, monkeypatch):
        container = _container(stop_timeout=90)
        monkeypatch.setattr(docker_utils, "get_docker_client_async", _client_cm_factory(container))

        assert await docker_utils.docker_action("Icarus", action) is True
        getattr(container, action).assert_called_once_with(timeout=90)

    async def test_restart_without_stop_timeout_keeps_default(self, monkeypatch):
        container = _container()
        monkeypatch.setattr(docker_utils, "get_docker_client_async", _client_cm_factory(container))

        assert await docker_utils.docker_action("Icarus", "restart") is True
        container.restart.assert_called_once_with()
