# -*- coding: utf-8 -*-
"""The Docker boundary holds at its edges, not only in the proxy's request check.

THE ADVERSARIAL REVIEW OF 2026-09-27 found the request handling sound and the
edges around it thinner:

* THE ROOT-PHASE CHOWN FOLLOWED LINKS. "find ... ! -type l -exec chown ...
  -exec chmod ..." checked "not a link" at listing time; chown and chmod then
  followed whatever the path had become. Root could be made to hand the
  entrypoint or the proxy to the app user's uid. scripts/fix_ownership.py now
  walks by directory descriptors and changes each entry through its own
  O_NOFOLLOW handle - exercised here on real files.
* A SOCKET IN THE ROOT GROUP LOCKED THE PROXY OUT (every call 502); ddcproxy
  now joins group root in that case.
* A SOCKET WHOSE GROUP IS THE PROXY USER'S OWN (2375) was open to ddc with no
  warning; the entrypoint warns, and - operator decision: warn, do not refuse -
  the panel shows a red notice whenever DDC could open the raw socket.
* THE PROXY RAN WITH PYTHONPATH=/app:... - safe only by module names; it now
  runs isolated (python3 -I).

COUNTER-CHECK (2026-09-27): red before on every case - no helper, the old
find/exec line, no root-group branch, no 2375 warning, no -I, no notice.
"""

import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = (ROOT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT / "scripts"))

UID, GID = os.getuid(), os.getgid()


@pytest.fixture
def helper():
    import fix_ownership
    return fix_ownership


def test_an_unusable_file_is_handed_over(helper, tmp_path):
    data = tmp_path / "config"
    data.mkdir()
    locked = data / "locked.json"
    locked.write_text("{}")
    locked.chmod(0)
    counts = helper.fix_tree(str(data), UID, GID)
    assert counts["fixed"] == 1
    assert stat.S_IMODE(locked.stat().st_mode) & 0o600 == 0o600


def test_a_link_inside_is_never_followed(helper, tmp_path):
    outside = tmp_path / "entrypoint.sh"
    outside.write_text("#!/bin/sh")
    outside.chmod(0)
    data = tmp_path / "config"
    data.mkdir()
    (data / "evil").symlink_to(outside)
    other = tmp_path / "opt"
    other.mkdir()
    (other / "proxy.py").write_text("x")
    (other / "proxy.py").chmod(0)
    (data / "evil_dir").symlink_to(other, target_is_directory=True)
    helper.fix_tree(str(data), UID, GID)
    assert stat.S_IMODE(outside.stat().st_mode) == 0, "a file behind a link was changed"
    assert stat.S_IMODE((other / "proxy.py").stat().st_mode) == 0, "a directory behind a link was entered"


def test_an_entry_swapped_for_a_link_at_the_last_moment_is_left_alone(helper, tmp_path):
    """The race itself: fix_entry is handed a name that has just become a link."""
    outside = tmp_path / "target"
    outside.write_text("x")
    outside.chmod(0)
    data = tmp_path / "config"
    data.mkdir()
    (data / "was_a_file").symlink_to(outside)
    fd = os.open(str(data), os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert helper.fix_entry("was_a_file", fd, UID, GID) == "skipped"
    finally:
        os.close(fd)
    assert stat.S_IMODE(outside.stat().st_mode) == 0


def test_a_second_name_for_a_file_is_left_alone(helper, tmp_path):
    outside = tmp_path / "entrypoint.sh"
    outside.write_text("x")
    outside.chmod(0)
    data = tmp_path / "config"
    data.mkdir()
    os.link(outside, data / "hardlink")
    helper.fix_tree(str(data), UID, GID)
    assert stat.S_IMODE(outside.stat().st_mode) == 0


def test_the_entrypoint_repairs_through_the_helper_only():
    assert 'FIX_OWNERSHIP="/app/scripts/fix_ownership.py"' in ENTRYPOINT
    assert 'python3 -I "$FIX_OWNERSHIP"' in ENTRYPOINT
    assert "-exec chown" not in ENTRYPOINT, "a chown that follows links is back"
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY scripts/fix_ownership.py /app/scripts/fix_ownership.py" in dockerfile


def test_a_root_group_socket_lets_the_proxy_in():
    assert 'addgroup "$PROXY_USER" root' in ENTRYPOINT


def test_a_socket_in_the_proxy_group_is_warned_about():
    assert '"$sock_gid" = "$(id -g "$PROXY_USER"' in ENTRYPOINT


def test_the_proxy_runs_isolated():
    assert "python3 -I '$PROXY_SCRIPT'" in ENTRYPOINT


def test_the_panel_says_when_the_raw_socket_is_open(monkeypatch):
    from app.web import security

    monkeypatch.setenv("DOCKER_HOST", "unix:///run/ddc-proxy/docker.sock")
    monkeypatch.setattr(security.os.path, "exists", lambda path: True)
    monkeypatch.setattr(security.os, "access", lambda path, mode: True)
    assert security.raw_docker_socket_open()
    monkeypatch.setattr(security.os, "access", lambda path, mode: False)
    assert not security.raw_docker_socket_open()
    template = (ROOT / "app" / "templates" / "_raw_socket_notice.html").read_text(encoding="utf-8")
    assert "raw_docker_socket_open" in template and "web.security.raw_socket_open" in template
    assert "_raw_socket_notice.html" in (ROOT / "app" / "templates" / "_base.html").read_text(encoding="utf-8")
