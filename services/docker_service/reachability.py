# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Is Docker reachable - and if not, is it DDC's proxy or Docker itself?

v3.0 puts the allowlist proxy (services/docker_proxy) between DDC and the
socket, a new thing that can fail. For /health, "the proxy is down" (restart
DDC) and "Docker is down" (the host's problem) are told apart:

* the proxy's socket cannot be opened      -> proxy_unreachable
* the proxy answers 502 (its daemon is gone) -> docker_unreachable
* without a proxy, the socket cannot be opened -> docker_unreachable

One raw ``GET /_ping`` - cheap enough for a healthcheck every 30 s, and no
docker-py client, which would first negotiate the API version.
"""

from __future__ import annotations

import os
import socket
from typing import Optional

PROXY_SOCKET = "/run/ddc-proxy/docker.sock"
DEFAULT_HOST = "unix:///var/run/docker.sock"


def _ping_status(path: str, timeout: float) -> Optional[int]:
    """HTTP status of GET /_ping on a unix socket; None if it cannot be opened."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(path)
    except OSError:
        conn.close()
        return None
    try:
        conn.sendall(b"GET /_ping HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n")
        # Until the status LINE is complete: one recv(64) could cut it after
        # "HTTP/1.1 ", and a healthy Docker was then reported as an error.
        head = b""
        while b"\r\n" not in head and len(head) < 256:
            chunk = conn.recv(64)
            if not chunk:
                break
            head += chunk
        parts = head.split(b"\r\n", 1)[0].split(b" ", 2)
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    except OSError:
        return 0
    finally:
        conn.close()


def _socket_path(host: str) -> str:
    """The socket path in a DOCKER_HOST, whatever spelling it uses."""
    if not host.startswith("unix://"):
        return ""
    rest = host[len("unix://"):]
    if rest.startswith("localhost/"):
        rest = rest[len("localhost"):]
    return rest.rstrip("/") or "/"


def docker_reachability(docker_host: Optional[str] = None, proxied: Optional[bool] = None,
                        timeout: float = 2.0) -> dict:
    host = docker_host or os.environ.get("DOCKER_HOST") or DEFAULT_HOST
    if proxied is None:
        # By the socket PATH, not by one exact spelling: docker-py accepts
        # "unix://localhost/path" and a trailing slash, and either of them used
        # to be called "direct" - so a dead proxy sent the operator to the host.
        proxied = _socket_path(host) == PROXY_SOCKET
    path_kind = "proxy" if proxied else "direct"
    if not host.startswith("unix://"):
        return {"path": path_kind, "state": "not_checked"}
    status = _ping_status(_socket_path(host), timeout)
    if status == 200:
        return {"path": path_kind, "state": "ok"}
    if status is None:
        return {"path": path_kind, "state": "proxy_unreachable" if proxied else "docker_unreachable"}
    if proxied and status == 502:
        return {"path": path_kind, "state": "docker_unreachable"}
    return {"path": path_kind, "state": "error"}
