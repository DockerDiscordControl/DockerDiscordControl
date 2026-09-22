# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The one place that builds a Docker client.

Until v2.4.1 eight places built their own client: two through the configured
``docker_socket_path``, three with a hard-coded ``unix:///var/run/docker.sock``,
the rest through ``DOCKER_HOST``. From v3.0 ``DOCKER_HOST`` points at the
allowlist proxy (services/docker_proxy), and every other way would walk past
it while still working - so no functional test would notice. Everything goes
through ``build_docker_client`` instead; tests/spec/test_every_docker_client_site_is_known.py
holds the remaining sites to zero.

* ``DOCKER_HOST`` (and docker-py's TLS variables) decide where the client
  goes, via ``docker.from_env``.
* Every caller names its timeout. The old sites used different ones on
  purpose (a 5 s diagnostic probe, Advanced Settings), and a shared default
  would drop them silently.
* The API version is negotiated once and reused. Without ``version=``,
  docker-py sends ``GET /version`` on every client it builds. A fixed pin was
  planned; measured on 2026-09-22, docker-py 7.1.0 defaults to API 1.44, which
  Docker older than 25 refuses, so the version is learned from the daemon
  once instead.
* ``docker_socket_path`` is retired. A non-default value is reported once,
  loudly, and not used.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import docker

logger = logging.getLogger("ddc.docker_client_factory")

DEFAULT_SOCKET_PATH = "/var/run/docker.sock"

_lock = threading.Lock()
_api_version: Optional[str] = None
_socket_path_checked = False


def _load_docker_config() -> dict:
    from services.config.config_service import load_config

    return (load_config() or {}).get("docker_config", {}) or {}


def _report_retired_socket_path() -> None:
    """Say once if the retired ``docker_socket_path`` is set to something else."""
    global _socket_path_checked
    if _socket_path_checked:
        return
    _socket_path_checked = True
    try:
        configured = _load_docker_config().get("docker_socket_path")
    except Exception as error:  # noqa: BLE001 - a courtesy must not stop Docker
        # Anything at all: the config import here is deferred on purpose (a
        # circular import at startup raises ImportError), and the call sites
        # catch only DockerException, OSError and RuntimeError - so this log
        # line used to be able to take all Docker access with it.
        logger.warning(f"Could not read docker_config to check docker_socket_path: {error}")
        return
    if configured and configured != DEFAULT_SOCKET_PATH:
        logger.warning(
            f"docker_config.docker_socket_path is set to '{configured}', but it is no longer "
            f"used since v3.0: every Docker client follows DOCKER_HOST. Set DOCKER_HOST instead "
            f"if the socket really lives elsewhere."
        )


def build_docker_client(*, timeout: float) -> docker.DockerClient:
    """Build a Docker client that follows ``DOCKER_HOST``.

    ``timeout`` is required and keyword-only: each caller has its own reason
    for its value.
    """
    global _api_version
    _report_retired_socket_path()
    with _lock:
        known = _api_version
    client = docker.from_env(timeout=timeout, version=known or "auto")
    if known is None:
        with _lock:
            _api_version = client.api.api_version
    return client


def _reset_for_tests() -> None:
    global _api_version, _socket_path_checked
    with _lock:
        _api_version = None
        _socket_path_checked = False
