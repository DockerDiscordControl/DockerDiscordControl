# -*- coding: utf-8 -*-
"""A newer image in the registry is reported once per new image (Phase 4d, part 2).

* The checker reports an update once per new remote digest - not every
  check, and again only when the registry moves on once more. When the local
  image catches up (the user pulled and recreated), it re-arms.
* A rule reacting to "image_update" may only notify: DDC cannot pull (the
  proxy refuses POST /images/create on purpose), so a restart would restart
  the OLD image - validation says so instead of accepting a rule that does
  nothing useful.
* The status loop starts the check at most once per interval, as a tracked
  background task, and only when such a rule exists.

COUNTER-CHECK (2026-09-22): red before; without the "already reported" memory
the checker reports the same update on every check.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule, validate_rule_data
from services.automation.image_updates import ImageUpdateChecker


def test_an_update_is_reported_once_per_new_image():
    checker = ImageUpdateChecker()
    first = checker.observe("web", "nginx:latest", remote="sha256:new", local={"sha256:old"})
    assert [(e.container, e.kind) for e in first] == [("web", "image_update")]
    assert "nginx:latest" in first[0].reason
    assert checker.observe("web", "nginx:latest", remote="sha256:new", local={"sha256:old"}) == []
    assert len(checker.observe("web", "nginx:latest", remote="sha256:newer", local={"sha256:old"})) == 1


def test_catching_up_re_arms():
    checker = ImageUpdateChecker()
    checker.observe("web", "nginx", remote="sha256:new", local={"sha256:old"})
    assert checker.observe("web", "nginx", remote="sha256:new", local={"sha256:new"}) == []
    assert len(checker.observe("web", "nginx", remote="sha256:next", local={"sha256:new"})) == 1


def test_unknown_is_never_an_update():
    checker = ImageUpdateChecker()
    assert checker.observe("web", "nginx", remote=None, local={"sha256:old"}) == []


def _rule(action_type):
    return {"name": "Updates", "trigger": {"type": "container_state", "states": ["image_update"]},
            "action": {"type": action_type}}


def test_an_image_update_rule_may_only_notify():
    assert validate_rule_data(_rule("NOTIFY"))[0]
    ok, error, _ = validate_rule_data(_rule("RESTART"))
    assert not ok and "pull" in error.lower()


@pytest.mark.asyncio
async def test_the_status_loop_starts_one_check_per_interval(monkeypatch):
    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    started = []

    async def fake_check(names, control):
        started.append(list(names))

    cog._check_image_updates = fake_check
    async def track(task):  # the cog's _track_task awaits the task it tracks
        await task

    cog._track_task = track
    rules = [AutoActionRule.from_dict(_rule("NOTIFY"))]
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: rules))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service",
                        lambda: SimpleNamespace(process_container_events=AsyncMock(return_value=[])))
    now = {"t": 0}
    monkeypatch.setattr(loops.time, "time", lambda: now["t"])
    results = {"web": SimpleNamespace(success=True, not_found=False, is_running=True, health=None,
                                      restart_count=0, cpu_percent=1.0, memory_percent=1.0)}
    for t in (0, 60, 7 * 3600):  # a check, too soon for another, then due again
        now["t"] = t
        await cog._feed_container_watchdog(results, {})
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    assert started == [["web"], ["web"]]
