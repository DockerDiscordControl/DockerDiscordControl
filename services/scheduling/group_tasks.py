# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""A scheduled task that acts on a group instead of one container.

Split out of scheduler.py (2026-09-23), which is on the size list and may only
shrink. The group is the operator's own (services/config/group_service.py), so
what it names can change under a task that was written months ago - which is
why three things here are NOT success.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from utils.logging_utils import get_module_logger

logger = get_module_logger('scheduler')


async def _timeout_for(container: str, action: str, timeout: int) -> float:
    """The timeout this container needs for this action (see scheduler._get_action_timeout)."""
    from services.scheduling.scheduler import (NON_REPEATABLE_ACTIONS, STOP_TIMEOUT_MARGIN_SECONDS,
                                               _get_container_stop_timeout)

    if action not in NON_REPEATABLE_ACTIONS:
        return timeout
    try:
        stop_timeout = await _get_container_stop_timeout(container)
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning(f"Stop timeout of {container} could not be read: {e}")
        return timeout
    if stop_timeout is None:
        return timeout
    return max(timeout, stop_timeout + STOP_TIMEOUT_MARGIN_SECONDS)


async def execute_group_task(task, timeout: int) -> bool:
    """Apply the task's action to every container of its group, one after another.

    The group is the operator's own (services/config/group_service.py), so what
    it names can change under a task that was written months ago. Three things
    are therefore NOT reported as success: a group that no longer exists, a
    group with nothing in it, and a group that names containers DDC no longer
    has - the last one would otherwise restart two of three and write "success"
    into the task list.

    The half second between two containers is the same pacing the bulk buttons
    use, counted by attempts so a daemon where every call fails is not hammered.
    """
    from services.config.group_service import get_group_service
    from services.docker_service.docker_action_service import docker_action_service_first

    def _record(success: bool, error: Optional[str]) -> bool:
        task.last_run_success = success
        task.last_run_error = error
        if error:
            logger.warning(f"Group task {task.task_id} ({task.container_name} {task.action}): {error}")
        from services.scheduling.scheduler import log_user_action

        log_user_action(
            action=f"{task.action.upper()}_GROUP" if success else f"{task.action.upper()}_GROUP_FAILED",
            target=task.container_name,
            user="Scheduled Task",
            source="Scheduled Task",
            details=f"Task ID: {task.task_id}, Group: {task.container_name}, Error: {error or '-'}")
        from services.scheduling.scheduler import _persist_executed_task

        task.update_after_execution()
        _persist_executed_task(task)
        return success

    try:
        members = get_group_service().members_of(task.container_name)
    except OSError as e:
        return _record(False, f"The groups could not be read: {e}")

    if not members.exists:
        return _record(False, f"The group '{task.container_name}' does not exist any more.")
    if not members.containers and not members.missing:
        return _record(False, f"The group '{task.container_name}' has no containers in it.")

    failed = []
    attempted = 0
    for container in members.containers:
        if attempted > 0:
            await asyncio.sleep(0.5)
        attempted += 1
        try:
            # Each member gets the time ITS container needs: the single-container
            # path raises the timeout to StopTimeout + margin for stop and
            # restart, and the group path used the raw 60 seconds for everyone -
            # a database with StopTimeout=120 was logged as failed every night
            # while the stop was still running.
            member_timeout = await _timeout_for(container, task.action, timeout)
            done = await asyncio.wait_for(docker_action_service_first(container, task.action),
                                          timeout=member_timeout)
        except asyncio.TimeoutError:
            done = False
            logger.error(f"Timeout on {task.action} for {container} (group {task.container_name})")
        except (RuntimeError, OSError) as e:
            done = False
            logger.error(f"Error on {task.action} for {container}: {e}", exc_info=True)
        if not done:
            failed.append(container)

    problems = []
    if failed:
        problems.append(f"{task.action} failed for: {', '.join(failed)}")
    if members.missing:
        problems.append(f"no longer in DDC: {', '.join(members.missing)}")
    return _record(not problems, "; ".join(problems) if problems else None)
