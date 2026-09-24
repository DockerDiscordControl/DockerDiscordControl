# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""A group in the places a container is offered.

OPERATOR DECISION (2026-09-24): a group behaves like ONE container, only with
several behind it. It is picked where a container is picked - the admin
button's list - and the buttons behind it are the same ones, because every
action goes through docker_action_service_first(), and "group:Icaruse" is a
name that understands (services/docker_service/group_actions.py).

The stack button that used to open a menu of groups and Compose stacks is gone
with this: what it could do, that list does, in the one place an operator
already looks for a container.

ITS OWN MODULE, not three more functions in control_ui.py. That file is on the
ceiling list and may not grow - and this is not a widget, it is the rule for
presenting a group as a container. Here, control_ui asks three short questions
instead of carrying the answers.
"""

from typing import Optional, Tuple

from services.config.group_service import group_target
from utils.logging_utils import get_module_logger

logger = get_module_logger('group_control')

# A group sorts after every container: the admin list is ordered by this number
# and a container's own order rarely passes a few dozen.
GROUP_ORDER = 9000

# What says "this is a group" in a list that also holds containers. The panel
# marks one with a collection icon in amber; a Discord dropdown option carries
# one emoji and no colour, so it is this - the same one the retired group menu
# used, which an operator who pressed that button already reads as "group".
GROUP_EMOJI = "🗂️"


def group_entries() -> list:
    """The operator's groups, shaped like the container entries beside them.

    Only groups that can actually be controlled: one that is switched off, or
    that is allowed nothing but status, would be an entry that wastes a press.
    """
    try:
        from services.config.group_service import get_group_service

        groups = get_group_service().get_groups()
    except OSError as e:
        # The containers are still offered; a failure here costs the groups,
        # not the menu.
        logger.error(f"Groups could not be read for the admin list: {e}")
        return []

    entries = []
    for group in groups:
        if not group.active:
            continue
        if not [action for action in group.allowed_actions if action != 'status']:
            continue
        entries.append({
            'name': group.name,
            'display': group.name,
            'docker_name': group_target(group.name),
            'order': GROUP_ORDER,
            'emoji': GROUP_EMOJI,
        })
    return entries


def controllable_entries(servers) -> list:
    """Everything the admin list may offer: the containers, then the groups.

    ONE LIST, ASKED TWICE. Two buttons open "choose something to control" -
    the one in control_ui.py and AdminOverviewAdminButton in admin_overview.py
    - and each built this from get_all_servers() on its own. Wiring the groups
    into one of them left the other exactly as it was, which is how a control
    channel ended up with no groups in its menu (operator, 2026-09-24).

    A display name stored as a LIST is what the panel writes for some
    containers; both old loops unwrapped it, and so does this one, or the
    dropdown reads "['Icarus 2', 'x']".
    """
    entries = []
    for server in servers or []:
        if not isinstance(server, dict):
            continue
        docker_name = server.get('docker_name') or server.get('container_name')
        if not docker_name:
            continue
        display = server.get('display_name', docker_name)
        if isinstance(display, list):
            display = display[0] if display else docker_name
        entries.append({
            'name': docker_name,
            'display': display or docker_name,
            'docker_name': docker_name,
            'order': server.get('order', 999),
        })
    return entries + group_entries()


def group_config_for(docker_name: str) -> Optional[dict]:
    """A group's configuration, shaped like a container's, or None.

    ITS OWN permissions, not its members' - that is the whole decision behind
    groups. ``allow_detailed_status`` is False because there is no single
    container to report cpu and memory for.
    """
    from services.docker_service.group_actions import group_name_of, is_group_target

    if not is_group_target(docker_name):
        return None
    try:
        from services.config.group_service import get_group_service

        group = get_group_service().find(group_name_of(docker_name))
    except OSError as e:
        logger.error(f"Groups could not be read for '{docker_name}': {e}")
        return None
    if group is None:
        return None
    return {
        'docker_name': docker_name,
        'container_name': group.name,
        'name': group.name,
        'display_name': group.name,
        'allowed_actions': list(group.allowed_actions),
        'allow_detailed_status': False,
        'active': group.active,
    }


def group_is_running(name: str, status_cache_service) -> bool:
    """Whether a group counts as running: when ANY member is.

    A group of two with one up gets both buttons, and either press does
    something - stopping the one that runs, starting the one that does not.
    Requiring all of them would hide the stop button on a half-started group,
    which is the moment an operator most wants it.
    """
    try:
        from services.config.group_service import get_group_service

        members = get_group_service().members_of(name)
    except OSError:
        return False
    for container in members.containers:
        entry = status_cache_service.get(container) if status_cache_service else None
        data = entry.get('data') if entry else None
        if data is not None and getattr(data, 'is_running', False):
            return True
    return False


async def running_state_for(cog, selected: str, config: dict) -> Tuple[bool, bool]:
    """(is_running, status_known) for whatever was picked in the admin list.

    A group has no container of its own to ask, so it is answered from its
    members; a container goes the ordinary way. Both answers decide the same
    thing - whether the stop button or the start button is drawn - which is
    why they are given in one place rather than branched at the call site.
    """
    from services.docker_service.group_actions import is_group_target

    if is_group_target(selected):
        return group_is_running(config.get('name'),
                                getattr(cog, 'status_cache_service', None)), True

    status_result = await cog.get_status(config)
    if not status_result.success:
        return False, False
    return status_result.is_running, True
