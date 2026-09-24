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

import discord

from cogs.translation_manager import _
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


async def wait_until_the_action_took_effect(cog, docker_name: str, display_name: str,
                                            action: str) -> Optional[bool]:
    """Wait for the action to show, refreshing the caches on the way.

    THE VERDICT IS THE POINT, and it used to be thrown away:

        True   the action showed - every member running after a start or a
               restart, none running after a stop
        False  the whole ladder ran out and it still had not
        None   there was nothing to ask about, so there is nothing to claim

    A caller that ignores False draws a container that never came up exactly
    like one that did (operator, 2026-09-24). It returns as soon as it knows,
    which is why nothing afterwards needs to wait on the clock.
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
            return True

    # The ladder ran out. Said plainly rather than as the last state seen: a
    # stop that left one member up is not "running", it is "not done".
    logger.warning(f"[ACTION_EFFECT] '{display_name}' did not show the '{action}' "
                   f"after {sum(RETRY_DELAYS)}s")
    return False if last_seen is not None else None


def not_confirmed_embed(display_name: str, action: str) -> discord.Embed:
    """What a press says when Docker took it but nothing confirmed it.

    The wait gives up after the capped ladder and used to hand that fact to
    nobody, so a container that never came up was drawn exactly like one that
    did - stopped, with no explanation (operator, 2026-09-24). It is not a
    failure: Docker accepted the command, and a game server can still be
    booting, which is why this is gold rather than red.

    The seconds come from the ladder, not from a number written out a second
    time - the panel start values were exactly that defect, one screen on.
    """
    embed = discord.Embed(
        title=_("⏱️ Not confirmed yet"),
        description=_("**{server_name}** was sent the {action_process_text} and Docker "
                      "accepted it, but the status had not changed after {seconds} "
                      "seconds. It may still be working.").format(
            server_name=display_name,
            action_process_text=f"({_(action.capitalize())})",
            seconds=sum(RETRY_DELAYS)),
        color=discord.Color.gold())
    embed.set_footer(text="https://ddc.bot")
    return embed
