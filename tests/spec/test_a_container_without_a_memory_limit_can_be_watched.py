# -*- coding: utf-8 -*-
"""A container without a --memory limit can trigger the memory rule at all.

THE PROBLEM, measured on the operator's server on 2026-09-23:

    26 containers running, 6 with a --memory limit, host RAM 62 GB
    the high_memory rule is a PERCENTAGE of the container's limit
    a container started without --memory has no limit, so Docker reports the
    HOST's total memory as the limit

    Enshrouded_Proton  8.3 GB of 62 GB  ->  13 %
    the rule's default threshold         ->  90 %  = 56 GB

So for 20 of 26 containers the rule can never fire, whatever the game server
does. The panel explains this in a hint, which is honest but does not help.

OPERATOR DECISION (2026-09-23): switch automatically. A container WITH a limit
keeps the percentage. A container WITHOUT one is measured against an absolute
threshold in MB. One rule, two yardsticks, picked per container - so no
existing rule changes meaning and the 20 become watchable.

WHY TWO WATCHERS AND NOT ONE CLEVERER ONE: ResourceWatcher already treats a
value of None as "not measured" and resets its timer. So the percentage watcher
is handed None for the unlimited containers and the MB watcher is handed None
for the limited ones. Neither one's logic changes; only the unit in the message
does. The alternative - one watcher holding two thresholds and a per-container
flag - would have put the branch inside the loop that decides when to alert,
which is the part that must stay simple.

HOW THIS TEST CAN FAIL: it gives a container without a limit more memory than
the MB threshold for long enough. No event is red.

COUNTER-CHECK (2026-09-23): red before - there was no MB threshold at all. The
other tests keep the existing behaviour: a container WITH a limit is still
measured in percent, and neither watcher reports the other's containers.
"""

import pytest

from services.automation.container_watch import HIGH_MEMORY, ResourceWatcher


def _run(watcher, values, minutes):
    """Observe twice: once to start the timer, once after the window."""
    watcher.observe(values, 1000.0)
    return watcher.observe(values, 1000.0 + minutes * 60 + 1)


def test_a_container_without_a_limit_is_reported_in_mb():
    """THE POINT: 8272 MB is over 4096 MB, whatever percent of the host it is."""
    watcher = ResourceWatcher("memory", 4096, 5, unit="MB")

    events = _run(watcher, {"Enshrouded_Proton": 8272.0}, 5)

    assert len(events) == 1, "a container far over the MB threshold was not reported"
    assert events[0].kind == HIGH_MEMORY
    assert "MB" in events[0].reason, events[0].reason
    assert "8272 MB" in events[0].reason and "4096 MB" in events[0].reason, events[0].reason


def test_a_container_below_the_mb_threshold_is_not_reported():
    """Counter-check: the threshold has to mean something."""
    watcher = ResourceWatcher("memory", 4096, 5, unit="MB")

    assert _run(watcher, {"Valheim": 2074.0}, 5) == []


def test_the_percentage_watcher_is_unchanged():
    """Counter-check: a container WITH a limit keeps its old yardstick."""
    watcher = ResourceWatcher("memory", 90, 5)

    events = _run(watcher, {"timergy-postgres": 93.0}, 5)

    assert len(events) == 1
    assert "%" in events[0].reason and "MB" not in events[0].reason, events[0].reason


def test_a_container_the_watcher_is_not_for_is_simply_not_measured():
    """How the split works: the other watcher is handed None, and None resets."""
    watcher = ResourceWatcher("memory", 4096, 5, unit="MB")

    assert _run(watcher, {"timergy-postgres": None}, 5) == []


def test_the_hysteresis_still_works_in_mb():
    """Counter-check: reported once, not once per poll."""
    watcher = ResourceWatcher("memory", 4096, 5, unit="MB")
    values = {"Enshrouded_Proton": 8272.0}

    first = _run(watcher, values, 5)
    again = watcher.observe(values, 1000.0 + 10 * 60)

    assert len(first) == 1
    assert again == [], "the same container was reported a second time"


def test_the_cpu_watcher_is_untouched():
    """Counter-check: the unit is memory's business only."""
    watcher = ResourceWatcher("cpu", 90, 5)

    events = _run(watcher, {"Icarus": 95.0}, 5)

    assert len(events) == 1
    assert "CPU" in events[0].reason and "%" in events[0].reason


# --- The wiring: where the two yardsticks come from and who gets which ---


def test_the_rule_carries_an_mb_threshold_that_survives_a_save():
    """The second yardstick has to be the operator's, not a constant."""
    from services.automation.auto_action_config_service import AutoActionRule

    data = {"id": "r", "name": "Hot", "action": {"type": "NOTIFY"},
            "trigger": {"type": "container_state", "states": ["high_memory"],
                        "memory_threshold_percent": 90, "memory_threshold_mb": 8192,
                        "resource_minutes": 5}}

    again = AutoActionRule.from_dict(AutoActionRule.from_dict(data).to_dict())

    assert again.trigger.memory_threshold_mb == 8192
    assert AutoActionRule.from_dict({**data, "trigger": {"type": "container_state"}}
                                    ).trigger.memory_threshold_mb == 4096, "the default"


def test_the_mb_range_cannot_overlap_the_percent_range():
    """Why this matters: an event carries only its number, and a rule accepts an
    event whose number is EITHER of its two thresholds. If 90 could mean both
    "90 %" and "90 MB", one rule's percent event could be claimed by another
    rule's MB threshold. Keeping the lowest MB above the highest percent makes
    that impossible instead of unlikely."""
    from services.automation.auto_action_config_service import (
        MAX_RESOURCE_PERCENT, MIN_RESOURCE_MB)

    assert MIN_RESOURCE_MB > MAX_RESOURCE_PERCENT


def test_validation_refuses_an_mb_threshold_out_of_range():
    """Counter-check: the range has to be enforced, not just declared."""
    from services.automation.auto_action_config_service import (
        MAX_RESOURCE_MB, MIN_RESOURCE_MB, validate_rule_data)

    def rule(mb):
        return {"id": "r", "name": "Hot", "action": {"type": "NOTIFY"},
                "trigger": {"type": "container_state", "states": ["high_memory"],
                            "memory_threshold_mb": mb}}

    assert validate_rule_data(rule(MIN_RESOURCE_MB))[0]
    assert validate_rule_data(rule(MAX_RESOURCE_MB))[0]
    assert not validate_rule_data(rule(MIN_RESOURCE_MB - 1))[0]
    assert not validate_rule_data(rule(MAX_RESOURCE_MB + 1))[0]


def test_the_cache_says_whether_a_container_has_a_limit():
    """Where "limited" comes from: HostConfig.Memory in the inspect answer, not
    from the stats limit - the stats limit is the host's RAM when there is none,
    which is exactly the number that cannot be told apart."""
    from cogs.status_handlers import _watch_fields

    unlimited = _watch_fields({"_computed": {"memory_usage_mb": 8272.0,
                                             "memory_limit_mb": 63500.0,
                                             "memory_limited": False}})
    limited = _watch_fields({"_computed": {"memory_usage_mb": 512.0,
                                           "memory_limit_mb": 1024.0,
                                           "memory_limited": True}})

    assert unlimited["memory_mb"] == 8272.0 and unlimited["memory_limited"] is False
    assert limited["memory_percent"] == 50.0 and limited["memory_limited"] is True


@pytest.mark.asyncio
async def test_the_status_loop_measures_an_unlimited_container_in_mb(monkeypatch):
    """THE POINT, end to end: the container that could never fire now does."""
    events = await _watchdog_events(monkeypatch, memory_mb=8272.0, memory_percent=13.0,
                                    memory_limited=False)

    assert [(e.container, e.kind, e.threshold) for e in events] == [("Enshrouded", "high_memory", 4096)]


@pytest.mark.asyncio
async def test_the_status_loop_still_measures_a_limited_container_in_percent(monkeypatch):
    """Counter-check: the 6 containers that DO have a limit keep the old rule."""
    events = await _watchdog_events(monkeypatch, memory_mb=980.0, memory_percent=95.0,
                                    memory_limited=True)

    assert [(e.container, e.kind, e.threshold) for e in events] == [("Enshrouded", "high_memory", 90)]


@pytest.mark.asyncio
async def test_a_container_whose_yardstick_is_unknown_is_measured_by_neither(monkeypatch):
    """Counter-check: "nothing said which kind this is" must not be read as
    either yardstick. That is memory_limited None - an older cache entry, or a
    result built before the flag existed - and both watchers are handed None.
    Guessing here would measure a 62 GB host as a container."""
    events = await _watchdog_events(monkeypatch, memory_mb=8272.0, memory_percent=95.0,
                                    memory_limited=None)

    assert events == []


def test_a_rule_accepts_an_event_from_either_of_its_thresholds():
    """Both watchers report for the SAME rule, so the engine has to own both."""
    from services.automation.auto_action_config_service import AutoActionRule
    from services.automation.automation_service import AutomationService
    from services.automation.container_watch import WatchEvent

    rule = AutoActionRule.from_dict({"id": "r", "name": "Hot", "action": {"type": "NOTIFY"},
                                     "trigger": {"type": "container_state", "states": ["high_memory"],
                                                 "memory_threshold_percent": 90,
                                                 "memory_threshold_mb": 4096, "resource_minutes": 5}})
    mine = AutomationService._measured_by_this_rule

    assert mine(WatchEvent("a", HIGH_MEMORY, "x", threshold=90, window_minutes=5), rule)
    assert mine(WatchEvent("a", HIGH_MEMORY, "x", threshold=4096, window_minutes=5), rule)
    assert not mine(WatchEvent("a", HIGH_MEMORY, "x", threshold=70, window_minutes=5), rule)


async def _watchdog_events(monkeypatch, *, memory_mb, memory_percent, memory_limited):
    """One container over both yardsticks, watched for the whole window."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog
    from services.automation.auto_action_config_service import AutoActionRule

    rules = [AutoActionRule.from_dict({"id": "r", "name": "Hot", "action": {"type": "NOTIFY"},
                                       "trigger": {"type": "container_state", "states": ["high_memory"],
                                                   "memory_threshold_percent": 90,
                                                   "memory_threshold_mb": 4096, "resource_minutes": 1}})]
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: rules))
    engine = SimpleNamespace(process_container_events=AsyncMock(return_value=[]))
    monkeypatch.setattr("services.automation.automation_service.get_automation_service", lambda: engine)
    ticks = [0, 30, 61, 90]
    monkeypatch.setattr(loops.time, "monotonic",
                        lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    results = {"Enshrouded": SimpleNamespace(
        success=True, not_found=False, is_running=True, health=None, restart_count=0,
        cpu_percent=5.0, memory_percent=memory_percent, memory_mb=memory_mb,
        memory_limited=memory_limited)}
    for _ in range(4):
        await cog._feed_container_watchdog(results, {})
    return [e for call in engine.process_container_events.await_args_list for e in call.args[0]]


# --- The panel: the operator has to be able to set the second yardstick ---


def test_the_rule_editor_offers_the_mb_threshold():
    """A setting nobody can reach is not a setting. The field's own min/max come
    from the same constants the server validates against, so the panel cannot
    offer a number the save then refuses."""
    from pathlib import Path

    from services.automation.auto_action_config_service import MAX_RESOURCE_MB, MIN_RESOURCE_MB

    modal = (Path(__file__).resolve().parents[2] / "app" / "templates"
             / "_auto_actions_modal.html").read_text(encoding="utf-8")
    position = modal.index('id="aasRuleMemoryThresholdMb"')
    field = modal[modal.rindex("<div", 0, position):modal.index("</div>", position)]

    assert f'min="{MIN_RESOURCE_MB}"' in field and f'max="{MAX_RESOURCE_MB}"' in field, field
    assert "web.aas.memory_threshold_mb" in modal


def test_the_editor_loads_and_saves_the_mb_threshold():
    """Counter-check: a field the JavaScript never reads is decoration."""
    from pathlib import Path

    script = (Path(__file__).resolve().parents[2] / "app" / "static" / "js"
              / "auto_actions.js").read_text(encoding="utf-8")

    assert "rule.trigger.memory_threshold_mb" in script, "the editor does not load it"
    assert "memory_threshold_mb: safeInt" in script, "the editor does not save it"


def test_every_locale_names_the_new_field():
    """A web string needs a key in every catalogue, not just en and de."""
    import json
    from pathlib import Path

    locales = [p for p in (Path(__file__).resolve().parents[2] / "locales").glob("*.json")
               if p.name != "meta.json"]

    assert len(locales) >= 40
    missing = [p.name for p in locales
               if "web.aas.memory_threshold_mb" not in json.loads(p.read_text(encoding="utf-8"))]
    assert missing == [], missing


def test_the_hint_now_names_both_yardsticks():
    """The old hint said the percentage was useless without a limit and left it
    there. It now has to say what happens instead."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for language in ("en", "de"):
        hint = json.loads((root / "locales" / f"{language}.json").read_text(encoding="utf-8"))[
            "web.aas.memory_threshold_hint"].lower()
        assert "mb" in hint, (language, hint)
        assert "--memory" in hint, (language, hint)
