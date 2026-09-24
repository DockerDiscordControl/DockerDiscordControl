# -*- coding: utf-8 -*-
"""After a button press, the wait asks about whatever was acted on.

FROM THE OPERATOR'S LOG (2026-09-24), a start on a container group:

    17:57:20  START action for 'Icaruse' ... success=True
    17:57:23  Getting status for Icaruse (attempt 1/6, waited 3s total)
    17:57:26  ... attempt 2/6, waited 6s
    17:57:31  ... attempt 3/6, waited 11s
    17:57:36  ... attempt 4/6, waited 16s
    17:57:41  ... attempt 5/6, waited 21s
    17:57:46  ... attempt 6/6, waited 26s
    17:57:47  Showing processing message for Icaruse
    17:58:02  Waiting 15 seconds for Icaruse to stabilize...

THE GROUP HAD ALREADY STARTED at 17:57:20. The six attempts looked up a
container called "Icaruse", found none - a group is not in the container list -
and so never even asked Docker anything. The loop slept its whole ladder, 26
seconds, and the press took 41 seconds to finish. Every group press does this.

WORSE THAN SLOW: the loop is also what refreshes the status caches after an
action. Skipping it left every member of the group on its pre-action cached
status, so the panel and the overview were redrawn from stale numbers.

SO THE WAIT IS NOT SKIPPED FOR A GROUP - IT IS POINTED AT THE GROUP. Members
take time to come up exactly as a single container does, so the same ladder
runs, asking each member and stopping as soon as they all match what was asked
for: every member running after start or restart, none running after stop.

IT LIVES OUTSIDE control_ui.py. That file is on the ceiling list and may not
grow, and the wait is not about a button - it is about what a Docker action did
to a container or a group. Moving it took control_ui.py from 3422 lines to 3367.

HOW THIS TEST CAN FAIL: a wait that asks the container machinery about a group,
or one that stops before the thing it acted on has caught up.

COUNTER-CHECK (2026-09-24): red before - the module did not exist, and the
behaviour it pins was a 26-second sleep.
"""

import asyncio
from types import SimpleNamespace

import pytest


class _Cache:
    def __init__(self):
        self.entries = {}
        self.removed = []

    def get(self, name):
        return self.entries.get(name)

    def remove(self, name):
        self.removed.append(name)
        self.entries.pop(name, None)

    def set(self, name, value, when):
        self.entries[name] = value


class _Cog:
    """Only what the wait touches."""

    def __init__(self, states):
        self.states = states              # docker_name -> is_running
        self.status_cache_service = _Cache()
        self.asked = []

    async def get_status(self, config):
        name = config.get("docker_name")
        self.asked.append(name)
        return SimpleNamespace(success=True, is_running=self.states[name],
                               display_name=name)


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Two containers, and a group holding both."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()

    servers = [{"docker_name": "alpha", "name": "alpha", "allowed_actions": ["start"]},
               {"docker_name": "beta", "name": "beta", "allowed_actions": ["start"]}]

    from services.config import group_service

    group_service.reset_group_service()
    for name in ("alpha", "beta"):
        (containers / f"{name}.json").write_text(
            '{"container_name": "%s", "docker_name": "%s", "active": true}' % (name, name),
            encoding="utf-8")
    group_service.get_group_service().save_group("Gameserver", ["alpha", "beta"])

    from cogs import action_effect

    monkeypatch.setattr(action_effect, "_all_servers", lambda: servers)
    # The ladder is the point of the timing cases, not the wall clock.
    slept = []

    async def _no_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(action_effect.asyncio, "sleep", _no_sleep)
    return SimpleNamespace(module=action_effect, servers=servers, slept=slept)


def test_a_group_is_asked_about_its_members(world):
    """THE FINDING: it looked for a container named like the group, found
    none, and asked nothing at all."""
    cog = _Cog({"alpha": True, "beta": True})

    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "start"))

    assert sorted(set(cog.asked)) == ["alpha", "beta"], cog.asked


def test_a_started_group_does_not_sit_out_the_whole_ladder(world):
    """26 seconds of sleeping after the work was already done."""
    cog = _Cog({"alpha": True, "beta": True})

    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "start"))

    assert sum(world.slept) <= 3, f"waited {sum(world.slept)}s after it was already up"


def test_a_group_that_is_only_half_up_keeps_waiting_after_a_start(world):
    """Start means all of them; stopping at the first one up would redraw the
    panel while the rest were still coming."""
    cog = _Cog({"alpha": True, "beta": False})

    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "start"))

    assert sum(world.slept) == 26, f"gave up after {sum(world.slept)}s"


def test_a_stop_waits_for_all_of_them_to_be_down(world):
    cog = _Cog({"alpha": False, "beta": True})

    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "stop"))

    assert sum(world.slept) == 26

    cog = _Cog({"alpha": False, "beta": False})
    world.slept.clear()
    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "stop"))

    assert sum(world.slept) <= 3


def test_the_members_caches_are_refreshed(world):
    """The wait is also what makes the panel and the overview read the new
    state. A group that skipped it was redrawn from what was cached before the
    action."""
    cog = _Cog({"alpha": True, "beta": True})

    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "start"))

    assert set(cog.status_cache_service.entries) == {"alpha", "beta"}


def test_a_container_still_goes_the_ordinary_way(world):
    cog = _Cog({"alpha": True, "beta": False})

    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "alpha", "alpha", "start"))

    assert cog.asked == ["alpha"]
    assert sum(world.slept) <= 3


def test_a_container_that_has_not_caught_up_is_waited_for(world):
    cog = _Cog({"alpha": False, "beta": False})

    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "alpha", "alpha", "start"))

    assert sum(world.slept) == 26
    assert len(cog.asked) == 6, cog.asked


def test_a_name_nothing_knows_does_not_raise(world):
    """A container removed from the configuration between the press and the
    wait: the press must still finish and redraw."""
    cog = _Cog({})

    asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "ghost", "ghost", "start"))

    assert cog.asked == []


def test_the_verdict_says_what_happened(world):
    """FOUND BY SABOTAGE (2026-09-24): making the wait always report success
    left every case green, because they all measured how long it slept and
    never what it concluded. The verdict is what the button shows the operator
    a notice by, so it is the part that must not lie.

        True   it showed
        False  the ladder ran out and it had not
        None   there was nothing to ask, so nothing is claimed
    """
    up = _Cog({"alpha": True, "beta": True})
    took = asyncio.run(world.module.wait_until_the_action_took_effect(
        up, "group:Gameserver", "Gameserver", "start"))

    assert took is True

    half = _Cog({"alpha": True, "beta": False})
    took = asyncio.run(world.module.wait_until_the_action_took_effect(
        half, "group:Gameserver", "Gameserver", "start"))

    assert took is False, "a group that never came up was reported as started"

    nothing = _Cog({})
    took = asyncio.run(world.module.wait_until_the_action_took_effect(
        nothing, "ghost", "ghost", "start"))

    assert took is None, "a name nothing knows must not be claimed either way"


def test_a_stop_that_left_one_running_is_not_success(world):
    """The sharpest form: "running" is true of the group, and the press was a
    stop. Reporting the last state seen instead of the verdict made that read
    as if something had worked."""
    cog = _Cog({"alpha": False, "beta": True})

    took = asyncio.run(world.module.wait_until_the_action_took_effect(
        cog, "group:Gameserver", "Gameserver", "stop"))

    assert took is False


def test_the_second_refresh_also_covers_a_group(world):
    """FOUND BY SABOTAGE (2026-09-24): removing this call left every case
    green. The button refreshes once more after its stabilising pause, and
    that pass was container-only too - so the overview was redrawn from the
    state from before the press, fifteen seconds further down the same
    callback."""
    cog = _Cog({"alpha": True, "beta": True})

    asyncio.run(world.module.refresh_the_caches(cog, "group:Gameserver"))

    assert sorted(set(cog.asked)) == ["alpha", "beta"], cog.asked
    assert set(cog.status_cache_service.entries) == {"alpha", "beta"}


def test_the_button_still_makes_that_second_pass(world):
    """The call site, or the refresh above is a function nobody runs."""
    from pathlib import Path as _Path

    source = (_Path(__file__).resolve().parents[2] / "cogs" / "control_ui.py").read_text(
        encoding="utf-8")

    assert "refresh_the_caches(self.cog, self.docker_name)" in source


def test_the_wait_left_control_ui(world):
    """It is not about a button, and control_ui.py is on the ceiling list."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "cogs" / "control_ui.py").read_text(
        encoding="utf-8")

    assert "wait_until_the_action_took_effect" in source
    assert "retry_delays = [3, 3, 5, 5, 5, 5]" not in source, (
        "the ladder is still written out in control_ui.py as well")
