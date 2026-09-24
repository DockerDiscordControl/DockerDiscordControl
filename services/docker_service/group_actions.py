# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Applying one action to every container of a group.

OPERATOR DECISION (2026-09-24): a group behaves like ONE container, "only with
several behind it". Everything in DDC that acts on a container calls
docker_action_service_first(name, action), so a group is a name like any
other - ``group:Icaruse``, the same spelling the auto-action rules already use
for their targets.

WHY THIS FILE EXISTS RATHER THAN A SECOND LOOP. services/scheduling/group_tasks.py
held this walk already: resolve the group, act on each member half a second
apart, report a partial run as a failure. A second copy in the action service
would be two code paths answering one question, drifting until a group
restarted from a button behaves differently from the same group restarted by a
task. There is one walk, and both callers ask it.

THE GROUP DECIDES, in one place: a group that is switched off does nothing,
and neither does one the operator did not allow that action. What it could not
reach is named in the outcome, never dropped - acting on four of seven and
calling it done is exactly what the group feature forbids.

THE PER-MEMBER TIMEOUT belongs to the caller. A scheduled stop gives each
container its own StopTimeout plus margin (a database with StopTimeout=120 was
logged as failed every night while the stop was still running); a button press
uses the plain timeout. So the timeout is a hook, not a constant.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from utils.logging_utils import get_module_logger

logger = get_module_logger('group_actions')

GROUP_PREFIX = "group:"

# The same pacing the bulk buttons use, counted by ATTEMPTS: tied to successes
# it would not pause at all on a daemon where every call fails, which is the
# very case it is for.
PACE_SECONDS = 0.5


@dataclass(frozen=True)
class GroupActionOutcome:
    """What happened, in the words a caller needs to report it."""
    success: bool
    acted: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    refused: Optional[str] = None

    def problem(self) -> Optional[str]:
        """One sentence for a log line or a task's error field, or None."""
        if self.refused:
            return self.refused
        problems = []
        if self.failed:
            problems.append(f"failed for: {', '.join(self.failed)}")
        if self.missing:
            problems.append(f"no longer in DDC: {', '.join(self.missing)}")
        return "; ".join(problems) if problems else None


def is_group_target(name: str) -> bool:
    """Whether this name is a group rather than a container."""
    return isinstance(name, str) and name.startswith(GROUP_PREFIX)


def group_name_of(name: str) -> str:
    return name[len(GROUP_PREFIX):] if is_group_target(name) else name


async def _act_on_one(container: str, action: str) -> bool:
    """One container, through the ordinary single-container path.

    Its own function so a test can stand in for it without reaching into the
    action service, and so this module never imports that service at module
    level (the service imports this one).

    TWO ARGUMENTS, not three. The timeout is enforced by the asyncio.wait_for
    around this call, exactly as it was before the walk moved here; handing it
    down as well would be a third argument that every stand-in in the suite
    would have to grow, for no change in behaviour.
    """
    from services.docker_service.docker_action_service import docker_action_service_first

    return await docker_action_service_first(container, action)


async def act_on_group(name: str, action: str, timeout: float = 30.0,
                       timeout_for: Optional[Callable] = None) -> GroupActionOutcome:
    """Apply ``action`` to every container of the group ``name``.

    ``timeout_for(container, action, timeout)`` is awaited per member when
    given, so a caller that knows a container needs longer can say so.
    """
    try:
        from services.config.group_service import get_group_service

        service = get_group_service()
        group = service.find(name)
        members = service.members_of(name)
    except OSError as e:
        logger.error(f"Groups could not be read for a {action} on '{name}': {e}")
        return GroupActionOutcome(False, refused=f"the groups could not be read: {e}")

    if group is None or not members.exists:
        return GroupActionOutcome(False, refused=f"the group '{name}' does not exist any more.")
    if not group.active:
        return GroupActionOutcome(False, refused=f"the group '{group.name}' is switched off.")
    if action not in group.allowed_actions:
        return GroupActionOutcome(
            False, refused=f"the group '{group.name}' is not allowed to {action}.")
    if not members.containers and not members.missing:
        return GroupActionOutcome(False, refused=f"the group '{group.name}' has no containers in it.")

    acted, failed = [], []
    attempted = 0
    for container in members.containers:
        if attempted > 0:
            await asyncio.sleep(PACE_SECONDS)
        attempted += 1
        member_timeout = timeout
        if timeout_for is not None:
            member_timeout = await timeout_for(container, action, timeout)
        try:
            done = await asyncio.wait_for(_act_on_one(container, action),
                                          timeout=member_timeout)
        except asyncio.TimeoutError:
            done = False
            logger.error(f"Timeout on {action} for {container} (group {group.name})")
        except (RuntimeError, OSError) as e:
            done = False
            logger.error(f"Error on {action} for {container}: {e}", exc_info=True)
        (acted if done else failed).append(container)

    outcome = GroupActionOutcome(
        success=not failed and not members.missing,
        acted=acted, failed=failed, missing=list(members.missing))
    if outcome.problem():
        logger.warning(f"Group {action} on '{group.name}': {outcome.problem()}")
    return outcome
