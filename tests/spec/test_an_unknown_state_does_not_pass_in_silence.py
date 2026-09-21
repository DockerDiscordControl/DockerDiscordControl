# -*- coding: utf-8 -*-
"""If "only if running" cannot be honoured, that has to be visible.

THE FINDING (review E25, services/automation/automation_service.py): an
Auto-Action rule can carry ``only_if_running``, and the code's own comment says
what it is for - *"don't touch a container that was stopped on purpose"*. It
guards ``{"RESTART", "RECREATE", "STOP"}``.

The check reads:

    if rule.only_if_running and action_type in ONLY_IF_RUNNING_ACTIONS:
        if await self._get_running_state(container) is False:
            ...skip...

``_get_running_state`` has three answers: True, False, and **None** when the
state could not be determined at all - ``get_docker_info`` raised, or came back
empty. Only a confirmed ``False`` skips, so an unknown state **runs the
action**: a container the operator had deliberately stopped gets RESTARTed,
which is precisely the harm the switch exists to prevent.

**The semantics are not changed here, and deliberately not.** The line above
that check says, in the code: *"Only a confirmed 'not running' skips; an
unknown state falls through to the action."* Somebody chose that, and there is
a real argument for it - failing closed means a transient Docker hiccup
silently stops automations from working at all. That trade-off belongs to the
operator, and it is written up in
`docs/quality/reviews/AUTOMATION_SERVICE.md` for them to decide.

What needed no decision: **nothing said so.** The safety switch the operator
turned on was quietly not honoured, the action ran, and the only record was a
WARNING about Docker from a different method that names neither the rule nor
the switch. If a container they stopped on purpose comes back up, there has to
be a line that explains it.
"""

import logging
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_an_undeterminable_state_is_reported(monkeypatch, caplog):
    from services.automation.automation_service import AutomationService

    service = AutomationService.__new__(AutomationService)

    async def unknown(_container):
        return None

    service._get_running_state = unknown

    rule = SimpleNamespace(only_if_running=True, name="restart on error", id="r1")

    with caplog.at_level(logging.DEBUG):
        skipped = await AutomationService._honours_only_if_running(
            service, rule, "RESTART", "minecraft")

    assert skipped is False, (
        "the semantics were changed: an unknown state must still run the "
        "action, which is what the code chose and what the operator has not "
        "been asked about yet"
    )
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "the 'only if running' switch could not be honoured and nothing said "
        "so - if a container the operator stopped on purpose comes back up, "
        "there is no line that explains it"
    )
    joined = " ".join(warnings)
    assert "minecraft" in joined, f"the container is not named: {joined!r}"
    assert "restart on error" in joined, f"the rule is not named: {joined!r}"


@pytest.mark.asyncio
async def test_a_confirmed_stop_still_skips(monkeypatch, caplog):
    """Counter-check: the switch must keep doing its job."""
    from services.automation.automation_service import AutomationService

    service = AutomationService.__new__(AutomationService)

    async def not_running(_container):
        return False

    service._get_running_state = not_running
    rule = SimpleNamespace(only_if_running=True, name="restart on error", id="r1")

    skipped = await AutomationService._honours_only_if_running(
        service, rule, "RESTART", "minecraft")

    assert skipped is True, "a container confirmed stopped was touched anyway"


@pytest.mark.asyncio
async def test_a_running_container_is_not_reported(caplog):
    """Counter-check: the normal case must stay quiet."""
    from services.automation.automation_service import AutomationService

    service = AutomationService.__new__(AutomationService)

    async def running(_container):
        return True

    service._get_running_state = running
    rule = SimpleNamespace(only_if_running=True, name="restart on error", id="r1")

    with caplog.at_level(logging.DEBUG):
        skipped = await AutomationService._honours_only_if_running(
            service, rule, "RESTART", "minecraft")

    assert skipped is False
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "a perfectly normal running container produced a warning"
    )
