# -*- coding: utf-8 -*-
"""A group's line in the overview does not guess what its members do.

THE FINDING (stage 4 review before v3.1.0, section 05, both passes,
verified 2026-09-29 in a corrected form). group_status_lines read the
status cache without the rules the container lines above it use - no age
limit, no .success check. When the members had no usable entry (Docker
unreachable, right after a start, an error entry) the container lines read
🔄 and the group line counted them as not running: 🔴 0/N, a guessed "all
down". With a long cache duration it could also draw 🟢 over members
whose data had expired.

THE CONTRACT: one rule decides whether a cached status is usable - for the
container lines and the group lines alike (fresh_status); a group with a
member of unknown state is drawn 🔄, not 🔴 or 🟢.

HOW THIS TEST CAN FAIL: the group line reads the cache its own way again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.docker_status.models import ContainerStatusResult


def _result(running=True):
    return ContainerStatusResult.success_result(
        docker_name="a", display_name="a", is_running=running, cpu="1%", ram="1MB",
        uptime="1m", details_allowed=True)


class _Cache:
    def __init__(self, entries):
        self.entries = entries

    def get(self, name):
        return self.entries.get(name)


@pytest.fixture
def group(monkeypatch):
    members = SimpleNamespace(containers=["a", "b"], missing=[])
    service = SimpleNamespace(
        get_groups=lambda: [SimpleNamespace(name="Games", active=True, allowed_actions=["status"])],
        members_of=lambda name: members)
    monkeypatch.setattr("services.config.group_service.get_group_service", lambda: service)


def _line(cache):
    from cogs.overview_embeds import group_status_lines
    lines = group_status_lines(cache, lambda s: s)
    return next(line for line in lines if "Games" in line)


def test_members_without_data_are_not_all_down(group):
    assert not _line(_Cache({})).lstrip("│ ").startswith("🔴")


def test_expired_data_is_not_green(group, monkeypatch):
    monkeypatch.setenv("DDC_DOCKER_MAX_CACHE_AGE", "300")
    old = datetime.now(timezone.utc) - timedelta(seconds=400)
    cache = _Cache({n: {"data": _result(True), "timestamp": old} for n in ("a", "b")})

    assert not _line(cache).lstrip("│ ").startswith("🟢")


def test_fresh_data_still_decides(group):
    """Counter-check."""
    now = datetime.now(timezone.utc)
    cache = _Cache({n: {"data": _result(True), "timestamp": now} for n in ("a", "b")})

    assert _line(cache).lstrip("│ ").startswith("🟢")
