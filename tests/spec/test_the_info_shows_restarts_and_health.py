# -*- coding: utf-8 -*-
"""The container info shows the restart count and the health check (Phase 4e).

Roadmap Phase 4e: "runtime and restart counter in the info modal". They came
from the status cache through StatusInfoButton._get_status_info until v3.1.0;
since then the info display reads the container from Docker when it is opened
(services/infrastructure/container_facts_service.py) and the count, the health
and the restart policy come from that one answer - the policy in the same line
as the count (operator, 2026-09-28: "🔁 restarts on its own" and "🔄 Restarts:
0" read as the same thing twice).

COUNTER-CHECK (2026-09-22): red before; with no cache entry the info adds
nothing - no invented zero. Again 2026-09-28 on the new source: with the
count read as 0 where Docker says nothing, the nothing-known case went red;
with the policy on a line of its own, the one-line case did.
"""

from cogs.info_extras import format_facts
from services.infrastructure.container_facts_service import ContainerFacts, facts_from_attrs


def test_restarts_and_health_are_read_from_docker():
    facts = facts_from_attrs({"RestartCount": 3, "State": {"Running": True, "Health": {"Status": "unhealthy"}}})
    text = "\n".join(format_facts(facts, details=False))
    assert "Restarts: 3" in text and "unhealthy" in text


def test_no_health_check_means_no_health_line():
    text = "\n".join(format_facts(facts_from_attrs({"RestartCount": 0, "State": {"Running": True}}), details=False))
    assert "Restarts: 0" in text and "health" not in text.lower()


def test_nothing_known_means_nothing_shown():
    assert format_facts(None, details=True) == []
    assert facts_from_attrs({"State": {}}).restart_count is None, "an unknown count became a zero"
    assert format_facts(ContainerFacts(), details=False) == []


def test_the_count_and_what_restarts_it_share_one_line():
    lines = format_facts(ContainerFacts(restart_count=0, restart_policy="unless-stopped"), details=True)
    restart_lines = [line for line in lines if "🔄" in line or "🔁" in line]
    assert restart_lines == ["🔄 Restarts: 0 · Restarts on its own after a crash or a reboot"], lines
