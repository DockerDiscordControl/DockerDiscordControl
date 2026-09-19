# -*- coding: utf-8 -*-
# @covers Z8
"""Z8 - a container left locked by a failed auto-action rule must not go unnoticed.

``AutomationService.process_message`` locks every target container before a
rule runs. If the rule then fails, it releases those locks again - otherwise
the containers stay blocked for the rule cooldown, 24 h by default.

THE FINDING (2026-09-19, Z8 sweep): if that RELEASE failed, it was logged at
DEBUG only, and the ERROR line right after it said "released its container
cooldowns" regardless. So the log claimed the opposite of what happened, and
the container silently stayed out of reach of every auto-action rule for up
to a day - a comment (here: a log line) stronger than its code.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.automation_service import AutomationService, TriggerContext


def _run(release_fails, caplog):
    service = AutomationService.__new__(AutomationService)
    rule = SimpleNamespace(name="Update restart", id="r1", priority=1,
                           action=SimpleNamespace(containers=["valheim"]))
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True}
    service.config_service.get_rules.return_value = [rule]
    service.state_service = MagicMock()
    if release_fails:
        service.state_service.release_execution_lock.side_effect = OSError("disk full")
    service._pre_filter_rules = lambda rules, context: list(rules)
    service._check_match = AsyncMock(return_value=(True, "keyword"))
    service._execute_rule = AsyncMock(side_effect=OSError("docker socket blip"))
    context = TriggerContext(message_id="1", channel_id="9", guild_id="2", user_id="3",
                             username="watcher", is_webhook=False,
                             content="Server update available", embeds_text="")
    with caplog.at_level(logging.DEBUG):
        asyncio.run(service.process_message(context))
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_failed_release_is_an_error_naming_the_container(caplog):
    errors = _run(release_fails=True, caplog=caplog)
    assert any("valheim" in m for m in errors), (
        f"The cooldown of 'valheim' could not be released - it stays locked for up to "
        f"24 h - and no ERROR says so: {errors}"
    )


def test_the_log_does_not_claim_a_release_that_failed(caplog):
    errors = _run(release_fails=True, caplog=caplog)
    assert not any("released its container cooldowns" in m for m in errors), errors


def test_a_successful_release_is_still_reported(caplog):
    """Counter-check: the honest message must not vanish when all goes well."""
    errors = _run(release_fails=False, caplog=caplog)
    assert any("released its container cooldowns" in m for m in errors), errors
