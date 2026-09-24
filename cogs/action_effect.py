# -*- coding: utf-8 -*-
"""Waiting until a Docker action has actually taken effect.

This used to sit inside the action button's callback in control_ui.py, written
for a container and only for a container. The operator pressed start on a
container group on 2026-09-24 and it cost him 41 seconds: the loop looked up a
container named like the group, found none - a group is not in the container
list - and slept its whole ladder without asking Docker anything. The caches it
also refreshes were left untouched, so the panel and the overview were then
redrawn from the state from before the press.

It is not about a button. It is about what an action did to a container or to a
group, which is why it lives here now, and why control_ui.py went from
3422 lines to 3367 (that file is on the ceiling list and may not grow).

THE LADDER IS THE SAME FOR BOTH. Game servers take 15-30 seconds to come up and
the members of a group are game servers; a group is simply asked about all of
its members, and the wait ends as soon as they all match what was asked for.
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from services.config.group_service import group_name_of, is_group_target
from utils.logging_utils import get_module_logger

logger = get_module_logger('control_ui')

# Some containers (like game servers) can take 15-30+ seconds to fully start.
RETRY_DELAYS = (3, 3, 5, 5, 5, 5)          # up to 26 seconds


def _all_servers() -> List[dict]:
    """Seam: the configured containers, as one call the tests can replace."""
    from services.config.server_config_service import get_server_config_service

    return get_server_config_service().get_all_servers()


def _targets(docker_name: str) -> List[dict]:
    """The container configurations one press has to wait for.

    A container waits for itself. A group waits for its members - looked up by
    docker_name, because a member named in groups.json that no longer exists
    must drop out rather than stall the wait.
    """
    servers = _all_servers()
    if not is_group_target(docker_name):
        return [server for server in servers
                if server.get('docker_name') == docker_name]

    try:
        from services.config.group_service import get_group_service

        wanted = set(get_group_service().members_of(group_name_of(docker_name)).containers)
    except OSError as error:
        logger.error(f"[ACTION_EFFECT] Could not read the group {docker_name}: {error}")
        return []
    return [server for server in servers if server.get('docker_name') in wanted]


def _has_taken_effect(action: str, running: List[bool]) -> bool:
    """Whether the states seen match what the press asked for.

    ALL of them, not any: a start that stopped at the first member up would
    redraw the panel while the rest were still coming, which is the "acts on
    fewer and reports done" this whole feature was built against.
    """
    if not running:
        return False
    if action == "stop":
        return not any(running)
    return all(running)                     # start, restart


async def refresh_the_caches(cog, docker_name: str) -> None:
    """Drop and refill the cached status of whatever was acted on.

    The button does this once more after its stabilising pause. Written for a
    container it refreshed nothing at all for a group, so the overview was
    redrawn from the state from before the press - the same gap as in the wait,
    fifteen seconds further down the same callback.
    """
    from services.infrastructure.container_status_service import get_container_status_service

    container_status_service = get_container_status_service()
    for server in _targets(docker_name):
        name = server.get('docker_name')
        if cog.status_cache_service.get(name):
            cog.status_cache_service.remove(name)
        container_status_service.invalidate_container(name)
        status = await cog.get_status(server)
        if status.success:
            cog.status_cache_service.set(name, status, datetime.now(timezone.utc))


async def wait_until_the_action_took_effect(cog, docker_name: str, display_name: str,
                                            action: str) -> Optional[bool]:
    """Wait for the action to show, refreshing the caches on the way.

    Returns the last state seen, or None if nothing could be asked - a name the
    configuration no longer knows must still let the press finish and redraw.
    """
    from services.infrastructure.container_status_service import get_container_status_service

    container_status_service = get_container_status_service()
    last_seen: Optional[bool] = None

    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        await asyncio.sleep(delay)
        targets = _targets(docker_name)
        if not targets:
            # Nothing to ask. Said once, not six times, and then given up on:
            # sleeping the rest of the ladder is what cost the group press its
            # 26 seconds.
            logger.info(f"[ACTION_EFFECT] Nothing configured for '{display_name}' - not waiting")
            return None

        running = []
        for server in targets:
            name = server.get('docker_name')
            # Both caches, or the answer is the one from before the action.
            if cog.status_cache_service.get(name):
                cog.status_cache_service.remove(name)
            container_status_service.invalidate_container(name)

            status = await cog.get_status(server)
            if not status.success:
                logger.error(f"[ACTION_EFFECT] Error getting status for {name}: {status}")
                continue
            cog.status_cache_service.set(name, status, datetime.now(timezone.utc))
            running.append(status.is_running)

        if running:
            last_seen = any(running) if action != "stop" else all(running)
        waited = sum(RETRY_DELAYS[:attempt])
        logger.info(f"[ACTION_EFFECT] {display_name}: {sum(running)}/{len(targets)} running "
                    f"after '{action}' (attempt {attempt}/{len(RETRY_DELAYS)}, {waited}s)")

        if _has_taken_effect(action, running):
            return last_seen

    return last_seen
