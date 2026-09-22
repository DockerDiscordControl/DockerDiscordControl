# -*- coding: utf-8 -*-
"""A proxy that did not come up does not put DDC back on the raw socket.

THE FINDING: after the privilege drop the entrypoint decides how DDC reaches
Docker. It looked only for the proxy socket, and when that was missing and
the raw socket was writable - a host socket with mode 666, the documented
reason the boundary can be void - it exported DOCKER_HOST to the raw socket
with a warning naming `--user` as the cause. But the branch cannot tell
`--user` (no root phase, so no proxy was ever started) from "the root phase
tried and the proxy failed". In the second case v3.0's whole boundary was
quietly dropped, and the log said something that was not true.

The root phase now says that it started the proxy (DDC_PROXY_STARTED), and
the decision is its own function:

* proxy socket there -> through the proxy, and a warning if the raw socket is
  open to DDC as well (the proxy binds nothing then);
* no proxy socket but the root phase started one -> DOCKER_HOST stays on the
  proxy socket (its watchdog loop restarts it), and the log says container
  control does not work until it is back. No raw socket;
* no proxy socket and no root phase (--user) -> the raw socket, as before,
  because it is the only way left.

COUNTER-CHECK (2026-09-22): red before - the second case exported the raw
socket. The third case is the one that must keep working.
"""

import os
import re
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = (ROOT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")


def _function(name):
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", ENTRYPOINT, re.S | re.M)
    assert match, f"entrypoint has no function {name}()"
    return match.group(0)


def _run(*, proxy_socket: bool, raw_socket: bool, started: bool):
    workdir = tempfile.mkdtemp()
    proxy_path = os.path.join(workdir, "proxy.sock")
    raw_path = os.path.join(workdir, "docker.sock")
    keep = []
    for path, wanted in ((proxy_path, proxy_socket), (raw_path, raw_socket)):
        if wanted:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path)
            keep.append(server)
    script = f"""
set -u
PROXY_SOCKET="{proxy_path}"
DOCKER_SOCKET="{raw_path}"
DDC_PROXY_STARTED="{'1' if started else ''}"
DOCKER_HOST="unix://$PROXY_SOCKET"
log_info() {{ echo "INFO $*"; }}
log_warn() {{ echo "WARN $*"; }}
log_error() {{ echo "ERROR $*"; }}
{_function("choose_docker_path")}
choose_docker_path
echo "DOCKER_HOST=$DOCKER_HOST"
"""
    try:
        done = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=30)
    finally:
        for server in keep:
            server.close()
    return done.stdout + done.stderr


def test_the_proxy_socket_is_used_when_it_is_there():
    output = _run(proxy_socket=True, raw_socket=True, started=True)
    assert "DOCKER_HOST=unix://" in output and "proxy.sock" in output.split("DOCKER_HOST=")[-1]
    assert "allowlist proxy" in output


def test_a_failed_proxy_does_not_fall_back_to_the_raw_socket():
    output = _run(proxy_socket=False, raw_socket=True, started=True)
    assert "docker.sock" not in output.split("DOCKER_HOST=")[-1], (
        f"the boundary was dropped silently: {output}")
    assert "ERROR" in output


def test_a_container_started_with_user_still_reaches_docker():
    """Counter-check: without a root phase the raw socket is the only way left."""
    output = _run(proxy_socket=False, raw_socket=True, started=False)
    assert "docker.sock" in output.split("DOCKER_HOST=")[-1], output
    assert "--user" in output


def test_without_any_socket_it_says_so():
    output = _run(proxy_socket=False, raw_socket=False, started=False)
    assert "ERROR" in output
