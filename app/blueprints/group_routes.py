# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The panel's way in to the operator's container groups.

The groups themselves live in services/config/group_service.py. These routes
only carry them: a refusal from the service reaches the page with its reason,
and a group says which of its containers DDC no longer has, so the page can
warn instead of the operator finding out when a task acts on five of seven.
"""

import logging

from flask import Blueprint, jsonify, request

from app.auth import auth
from services.config.group_service import get_group_service
from utils.config_paths import get_config_dir

logger = logging.getLogger('ddc.web.group_routes')

group_bp = Blueprint('group_bp', __name__)


@group_bp.route('/api/groups', methods=['GET'])
@auth.login_required
def list_groups():
    """Every group, with the containers it names and the ones that are gone."""
    service = get_group_service()
    try:
        groups = []
        for group in service.get_groups():
            members = service.members_of(group.name)
            groups.append({
                "name": group.name,
                "containers": group.containers,
                "missing": members.missing,
                # The group's OWN permissions, not its members' - a group is a
                # control of its own (services/config/group_service.py).
                "active": group.active,
                "allowed_actions": group.allowed_actions,
            })
        return jsonify({"groups": groups})
    except OSError as e:
        # Not an empty list: the page would show "no groups" for a file that
        # could not be read, and the operator would build them a second time.
        logger.error(f"Groups could not be listed: {e}")
        return jsonify({"error": str(e)}), 500


def containers_on_the_host():
    """The names of the containers the host has, as the panel sees them.

    Its own function so the panel's docker cache is one named seam rather than
    an import in the middle of a save.
    """
    from app.utils.web_helpers import get_docker_containers_live

    containers, _error = get_docker_containers_live(logger)
    return [c.get('name') for c in (containers or []) if isinstance(c, dict) and c.get('name')]


def _make_members_steerable(names):
    """Give every named container DDC has no configuration for one of its own.

    THE GAP THIS CLOSES (measured 2026-09-24 on the operator's server: 26
    containers, 8 configured): a group resolves against config/containers/, so
    a container he had never configured was reported as one DDC no longer has -
    while the dialog offered it to him. It could be grouped and not acted on.

    INACTIVE, WITH NOTHING TICKED. He granted the GROUP, and what the group may
    do is the group's own list; joining one must not hand the container its own
    four buttons in Discord.

    ONLY CONTAINERS THE HOST ACTUALLY HAS. Writing a file for any name would
    make "this member is gone" impossible to report, because that report IS
    "DDC has no configuration for it" - a typo in a group would quietly become
    a container. Here in the route for the same reason: only the panel can ask
    the host.
    """
    try:
        known = set(containers_on_the_host())
    except (OSError, RuntimeError, ImportError, AttributeError, ValueError) as e:
        # The group itself is already saved. A daemon that does not answer must
        # not cost the operator what he just typed; the members stay reported as
        # missing until the host can be asked again.
        logger.warning(f"The host could not be asked which containers it has: {e}")
        return

    directory = get_config_dir() / "containers"
    from services.config.container_config_save_service import get_container_config_save_service

    service = get_container_config_save_service()
    for name in names:
        if name not in known or (directory / f"{name}.json").exists():
            continue
        written = service.save_container_config(name, {
            "container_name": name,
            "docker_name": name,
            "name": name,
            "active": False,
            "allowed_actions": [],
            "display_name": name,
        })
        if written:
            logger.info(f"'{name}' joined a group and was given a configuration "
                        f"(inactive, no permissions of its own)")
        else:
            logger.error(f"'{name}' joined a group but its configuration could not be "
                         f"written - the group cannot reach it")


@group_bp.route('/api/groups', methods=['POST'])
@auth.login_required
def save_group():
    """Create a group, or replace what the one with that name holds."""
    data = request.get_json(silent=True) or {}
    # None, not a default, when the caller says nothing: the service then keeps
    # what the group has instead of quietly resetting its permissions. An empty
    # list IS an answer - every box ticked off - and must survive as one.
    result = get_group_service().save_group(
        data.get("name"), data.get("containers") or [],
        active=data.get("active"),
        allowed_actions=(data.get("allowed_actions")
                         if isinstance(data.get("allowed_actions"), list) else None))
    if result.success:
        # After the group is stored, never instead of: a container that cannot
        # be written must not cost the operator the group.
        _make_members_steerable(data.get("containers") or [])
        return jsonify({"success": True})
    return jsonify({"success": False, "error": result.error}), 400


@group_bp.route('/api/groups/<name>', methods=['DELETE'])
@auth.login_required
def delete_group(name):
    """Remove a group. The containers themselves are not touched."""
    result = get_group_service().delete_group(name)
    if result.success:
        return jsonify({"success": True})
    # 404, not 400: the page asked for something that is not there, and a 200
    # would tell it a group vanished that never existed.
    return jsonify({"success": False, "error": result.error}), 404
