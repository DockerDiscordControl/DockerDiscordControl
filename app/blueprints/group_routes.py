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
