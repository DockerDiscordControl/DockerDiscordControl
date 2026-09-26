# -*- coding: utf-8 -*-
"""A CPU rule says what its percent is OF - one core, or the whole host.

THE FINDING (audit 2026-09-26, F9), measured live: DDC read 50.9 % for a
container `docker stats` showed at 50.4 % - percent of ONE core, which on the
operator's 12-core host goes up to 1200 %. The form allowed 10-100 and said
"CPU threshold (%)". So "90 %" meant 90 % of one core - one busy thread set it
off - and a container limited to half a core could never reach it.

OPERATOR DECISION (2026-09-26): make it a choice on the rule. cpu_basis
"core" is what it always was (existing rules keep their meaning) and may now
go above 100; "host" is percent of the whole machine, 10-100.

HOW THIS TEST CAN FAIL: a host rule measured per core, a core rule capped at
100, or an event of one basis handed to a rule of the other.

COUNTER-CHECK (2026-09-26): red before the fix - cpu_basis was dropped by the
model and a 400 % core threshold was refused.
"""

from types import SimpleNamespace

import pytest

from services.automation.auto_action_config_service import AutoActionRule, validate_rule_data


def _data(**trigger):
    base = {"type": "container_state", "states": ["high_cpu"], "cpu_threshold_percent": 80,
            "resource_minutes": 5}
    base.update(trigger)
    return {"id": "r", "name": "Hot", "trigger": base, "action": {"type": "NOTIFY"}}


def test_the_basis_survives_the_round_trip_and_defaults_to_core():
    assert AutoActionRule.from_dict(_data()).trigger.cpu_basis == "core"
    again = AutoActionRule.from_dict(AutoActionRule.from_dict(_data(cpu_basis="host")).to_dict())
    assert again.trigger.cpu_basis == "host"


@pytest.mark.parametrize("basis, value, ok", [
    ("core", 400, True), ("core", 90, True), ("host", 90, True),
    ("host", 400, False), ("core", 5, False), ("elsewhere", 90, False),
])
def test_validation_knows_the_ranges(basis, value, ok):
    assert validate_rule_data(_data(cpu_basis=basis, cpu_threshold_percent=value))[0] is ok


def test_a_host_rule_measures_percent_of_the_machine(monkeypatch):
    import cogs.background_loops as loops

    monkeypatch.setattr(loops.os, "cpu_count", lambda: 12)
    result = SimpleNamespace(is_running=True, cpu_percent=600.0)

    assert loops._measured_for(result, "cpu", loops.CPU_HOST_UNIT) == pytest.approx(50.0)
    assert loops._measured_for(result, "cpu", "%") == pytest.approx(600.0)


def test_an_event_reaches_only_the_rule_of_its_basis():
    from services.automation.automation_service import AutomationService
    from services.automation.container_watch import WatchEvent
    import cogs.background_loops as loops

    core = AutoActionRule.from_dict(_data(cpu_basis="core"))
    host = AutoActionRule.from_dict(_data(cpu_basis="host"))
    event = WatchEvent("web", "high_cpu", "hot", threshold=80, window_minutes=5, unit=loops.CPU_HOST_UNIT)

    assert AutomationService._measured_by_this_rule(event, host)
    assert not AutomationService._measured_by_this_rule(event, core)
