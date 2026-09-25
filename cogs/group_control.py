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
action goes through docker_action_service_first(), and "group:Gameserver" is a
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

import discord

from services.config.group_service import (group_target,  # noqa: F401
                                           is_group_target)
from utils.logging_utils import get_module_logger

from .translation_manager import _

logger = get_module_logger('group_control')

# A group sorts after every container: the admin list is ordered by this number
# and a container's own order rarely passes a few dozen.
GROUP_ORDER = 9000

# What says "this is a group" in a list that also holds containers.
#
# THE OPERATOR CHOSE IT (2026-09-24) after seeing the first one: the retired
# group menu's card-index emoji renders large and colourful on Discord and
# reads as clutter rather than as a collection. A folder is the calmest thing
# that says "there is more inside".
#
# AND ONLY THE GROUP CARRIES ONE. He was asked whether the containers should
# be marked too and chose not to: the group is the only row with a symbol, and
# it stands out for exactly that reason. A symbol on every row is a column the
# eye reads instead of an exception it notices.
#
# The panel writes the same mark in app/static/js/config-ui.js - it cannot
# import this one - and a test compares them, because two marks for one thing
# is how somebody ends up wondering whether they mean the same.
GROUP_EMOJI = "📁"


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
    dropdown reads "['Beta Server', 'x']".
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


def group_help_field():
    """(name, value) for the help's group section - the same in both helps.

    There are two help texts, `/help` and the ❓ button, and they are not
    copies: they document different things and had already drifted (only one
    of them ever explained the pending lamp). This section is the same in both
    by construction rather than by care.

    IT CALLS _() ITSELF rather than taking a translator as an argument. The
    check that every bot string is a catalogue key finds literals handed to
    the translation function as it is IMPORTED; a function passed in as a
    parameter is invisible to it, and these five sentences would have been the
    first ones nobody noticed missing.
    """
    return (
        f"**{_('Container groups')}**",
        f"{GROUP_EMOJI} {_('A group acts like a single container, with permissions of its own')}\n"
        f"🟢 {_('all of its containers are running')}"
        f" · 🟡 {_('some are running')}"
        f" · 🔴 {_('none is running')}"
        "\n\u200b")


def group_panel_embed(name: str, status_cache_service):
    """What the admin panel shows for a group: what its overview line says,
    with room.

    NOT A CONTAINER'S STATUS. The panel used to ask the status cache for
    "group:Gameserver", which is not a container, so it drew the error a missing
    container draws - "Could not retrieve status. Configuration missing or
    initial fetch failed" - under the group's own name (operator, 2026-09-24).
    """
    import discord

    try:
        from services.config.group_service import get_group_service

        service = get_group_service()
        group = service.find(name)
        members = service.members_of(name)
    except OSError as e:
        logger.error(f"Groups could not be read for the panel of '{name}': {e}")
        group, members = None, None

    if group is None or members is None or not members.exists:
        return discord.Embed(
            title=f"{GROUP_EMOJI} {name}",
            description=_("This group does not exist any more."),
            color=discord.Color.red())

    present = members.containers
    running = [container for container in present
               if _is_running(container, status_cache_service)]
    if running and len(running) == len(present):
        lamp, colour = "🟢", discord.Color.green()
    elif running:
        lamp, colour = "🟡", discord.Color.orange()
    else:
        lamp, colour = "🔴", discord.Color.red()

    lines = [f"{lamp} **{len(running)}/{len(present)}**"]
    for container in present:
        mark = "🟢" if container in running else "🔴"
        lines.append(f"{mark} `{container}`")
    if members.missing:
        # The same warning the panel and the overview give: a group acting on
        # fewer containers than it names must not look complete.
        lines.append("⚠️ " + _("No longer in DDC: {names}").format(
            names=", ".join(members.missing)))

    return discord.Embed(title=f"{GROUP_EMOJI} {group.name}",
                         description="\n".join(lines), color=colour)


def _is_running(container: str, status_cache_service) -> bool:
    entry = status_cache_service.get(container) if status_cache_service else None
    data = entry.get('data') if entry else None
    return bool(data is not None and getattr(data, 'is_running', False))


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
    return any(_is_running(container, status_cache_service)
               for container in members.containers)


async def admin_panel_embed(cog, channel_id, selected: str, config: dict, app_config,
                            display_name: str):
    """The finished embed of the admin panel, for whatever was picked.

    A group has no container to ask about, so asking drew the error a missing
    container draws - under the group's own name (operator, 2026-09-24). It
    gets the embed its overview line describes, with its own title and its own
    colour: both already say what it is and how much of it is up.

    ONE BUILDER FOR TWO PLACES. The panel is built when a target is picked and
    again after a button was pressed, and the second one still asked for a
    container status after the first had learned better - so a press on a group
    redrew the panel as an error over a group that had just done what it was
    told. A third place would make the same mistake a third time.
    """
    from .translation_manager import _ as translate

    cache = getattr(cog, 'status_cache_service', None)
    if is_group_target(selected):
        return group_panel_embed(config.get('name'), cache)

    embed, _view, _running = await cog._generate_status_embed_and_view(
        channel_id, selected, config, app_config)
    if not embed:
        return embed
    embed.title = translate("🛠️ Admin Control: {name}").format(name=display_name)
    running, known = await running_state_for(cog, selected, config)
    if not known:
        embed.color = discord.Color.gold()
    else:
        embed.color = discord.Color.green() if running else discord.Color.red()
    return embed


def admin_control_view(cog, container_config: dict, is_running: bool):
    """The button row for the PRIVATE admin panel, with its way out.

    One place, because both callers - the panel as it opens, and the panel
    rebuilt after an action - need the same four arguments and the same close
    button, and a second copy is where that button goes missing.

    THE CLOSE BUTTON BELONGS ONLY HERE. ControlView also builds the status and
    control channel overviews, which everybody in the channel reads; a close
    button on one of those would let any reader delete it for all of them. The
    operator asked for this explicitly, and
    tests/spec/test_only_a_private_panel_offers_a_close_button.py turns red if
    it ever reaches a public one.
    """
    # Imported here: control_ui imports this module, so naming it at the top
    # would close the circle.
    from .control_ui import ControlView
    from .ddc_ui import CloseButton

    view = ControlView(cog, container_config, is_running=is_running,
                       channel_has_control_permission=True)  # an admin always has it
    view.add_item(CloseButton())  # last on the action row
    return view


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
