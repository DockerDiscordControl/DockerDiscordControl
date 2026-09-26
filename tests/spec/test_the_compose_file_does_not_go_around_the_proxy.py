# -*- coding: utf-8 -*-
"""The shipped docker-compose.yml does not undo the allowlist proxy.

THE FINDING (audit 2026-09-26). The image sets DOCKER_HOST to the proxy's
socket for the whole container, so that `docker exec` sessions - the
documented reset_password.py and disable_2fa.py among them - take the same way
as DDC (Dockerfile, "DOCKER_HOST ... so docker exec sessions and diagnostics
take the same way"). The compose file set DOCKER_HOST back to the raw socket,
and offered `user: "99:100"` to uncomment - the one start mode in which no
proxy can run and DDC falls back to the raw socket. It also carried three
variables nothing reads (ENV_FLASK_SECRET_KEY "for Supervisor", which the
image has not had since v2, ENV_DOCKER_SOCKET, DOCKER_SOCKET).

HOW THIS TEST CAN FAIL: the compose file points DOCKER_HOST anywhere, sets or
offers `user:`, or brings a dead variable back.

COUNTER-CHECK (2026-09-26): red before the fix on all three cases.
"""

import re
from pathlib import Path

COMPOSE = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
SETTINGS = [line for line in COMPOSE.splitlines() if not line.lstrip().startswith("#")]


def test_docker_host_is_left_to_the_image():
    assert not any(re.match(r"\s*DOCKER_HOST\s*:", line) for line in SETTINGS), (
        "the compose file sets DOCKER_HOST, and the image's points at the proxy")


def test_no_user_is_set_or_offered():
    """Neither set nor waiting behind a '#': a line to uncomment is an invitation."""
    assert not re.search(r"^\s*#?\s*user\s*:", COMPOSE, re.M), (
        "a container started with --user runs no proxy")


def test_no_variable_nothing_reads():
    for name in ("ENV_FLASK_SECRET_KEY", "ENV_DOCKER_SOCKET", "DOCKER_SOCKET"):
        assert not any(re.match(rf"\s*{name}\s*:", line) for line in SETTINGS), name


def test_the_socket_is_still_mounted():
    """Counter-case: the proxy needs the socket inside the container."""
    assert "/var/run/docker.sock:/var/run/docker.sock" in COMPOSE
