# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Inline routes registered directly on the Flask app."""

from __future__ import annotations

import docker
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import Flask, jsonify, request

from app.auth import auth, session_user, verify_password
from services.admin.admin_service import get_admin_service
from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service


def _validate_admin_users(admin_users: List[str]) -> Dict[str, Any]:
    for user_id in admin_users:
        if not user_id.isdigit():
            return {"success": False, "error": f"Invalid user ID: {user_id}"}
    return {"success": True}


def _validate_admin_containers(admin_containers: Any,
                               admin_users: List[str]) -> Dict[str, Any]:
    """Check a per-admin container assignment before it is written (review F5).

    Every name is checked against the configured containers, because a typo
    does not fail - it silently means "this admin may control nothing on that
    one", and nothing would ever say so. The admin is simply refused later and
    nobody connects it to a letter. So an unknown name is refused here, by name.

    An id that is not on the admin list is refused as well: this mapping
    narrows a right, and writing one for somebody who has none is a statement
    nobody can act on.
    """
    if admin_containers is None:
        return {"success": True}
    if not isinstance(admin_containers, dict):
        return {"success": False, "error": "admin_containers must be an object"}

    try:
        from services.config.server_config_service import get_server_config_service
        known = {str(server.get("docker_name")) for server in
                 get_server_config_service().get_all_servers()
                 if isinstance(server, dict) and server.get("docker_name")}
    except (AttributeError, IOError, OSError, RuntimeError, TypeError, ValueError) as e:
        # A list of containers that cannot be read is not a reason to wave an
        # assignment through: it would be written with names nobody checked.
        # The details go to the log only; they can name host paths (CodeQL #64).
        logging.getLogger(__name__).error(
            "Configured containers could not be read for the admin assignment: %s",
            e, exc_info=True)
        return {"success": False,
                "error": "The configured containers could not be read. "
                         "See the log for details."}

    for user_id, containers in admin_containers.items():
        if str(user_id) not in {str(u) for u in admin_users}:
            return {"success": False,
                    "error": f"{user_id} is not on the admin list"}
        if not isinstance(containers, list):
            return {"success": False,
                    "error": f"The assignment for {user_id} is not a list"}
        for name in containers:
            if str(name) not in known:
                return {"success": False,
                        "error": f"No container is called '{name}'"}
    return {"success": True}


def register_routes(app: Flask) -> None:
    """Attach the admin management and health routes."""

    @app.route("/api/admin-users", methods=["GET", "POST"])
    @auth.login_required
    def admin_users():
        admin_service = get_admin_service()

        # The read had no guard at all, and the save caught only RuntimeError -
        # while a full disk, a permission problem or a corrupt admins.json raise
        # OSError or json.JSONDecodeError. The route then ended as an unhandled
        # 500 instead of the {"success": false, ...} it was written to return.
        # health_check() twenty lines below already catches the wider set; the
        # two handlers in one file did not agree on what can go wrong (review C21).
        _STORAGE_ERRORS = (IOError, OSError, PermissionError, RuntimeError,
                           TypeError, ValueError, json.JSONDecodeError)

        if request.method == "GET":
            try:
                data = admin_service.get_admin_data()
                # The names the panel may offer, from the SAME source the save
                # validates against, so a form cannot offer what the save then
                # refuses. An extra, not the point of this route: if the
                # container config cannot be read the admin list still goes out
                # and the choices are simply empty (review F5).
                try:
                    from services.config.server_config_service import get_server_config_service
                    data["available_containers"] = sorted(
                        {str(server.get("docker_name")) for server in
                         get_server_config_service().get_all_servers()
                         if isinstance(server, dict) and server.get("docker_name")})
                except _STORAGE_ERRORS as e:
                    app.logger.error("Container list for the admin panel could not be "
                                     "read: %s", e, exc_info=True)
                    data["available_containers"] = []
                return jsonify(data)
            except _STORAGE_ERRORS as e:
                app.logger.error("Error reading admin data: %s", e, exc_info=True)
                # 500, not the default 200 (review E22). fetch() does not reject
                # on an HTTP error, and it certainly does not reject on a 200, so
                # the panel ran its SUCCESS path over this error body: an empty
                # admin list, the modal opened saying "no users configured", and
                # the next Save wrote that empty list over the file that could
                # not be read. A read error must not be able to become a write
                # that erases what it failed to read.
                #
                # The body keeps its explanation (review C21) - a status code
                # says a request failed, not why.
                return jsonify({"success": False,
                                "error": "An internal error occurred while reading admin data"}), 500

        try:
            data = request.json or {}
            admin_users = data.get("discord_admin_users", [])
            admin_notes = data.get("admin_notes", {})
            # None, not {}: left out it means "leave the assignment on disk
            # alone". An empty mapping would DELETE every assignment, and every
            # caller that predates this feature passes nothing (review F5).
            admin_containers = data.get("admin_containers")

            validation = _validate_admin_users(admin_users)
            if not validation.get("success"):
                return jsonify(validation)

            validation = _validate_admin_containers(admin_containers, admin_users)
            if not validation.get("success"):
                return jsonify(validation)

            success = admin_service.save_admin_data(admin_users, admin_notes,
                                                    admin_containers=admin_containers)
            if success:
                return jsonify({"success": True})
            return jsonify({"success": False, "error": "Failed to save admin data"})
        except _STORAGE_ERRORS as e:
            # Security: Log detailed error server-side only, return generic message
            app.logger.error("Error saving admin data: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "An internal error occurred while saving admin data"})

    def _caller_is_logged_in():
        """Whether this request carries a login - either way in.

        /health has no decorator, on purpose: the container probe holds no
        credentials. So the two ways a human gets in are asked by hand - the
        panel's session cookie, and the Basic auth an operator types into curl.
        """
        if session_user():
            return True
        credentials = request.authorization
        return bool(credentials and verify_password(credentials.username,
                                                    credentials.password))

    @app.route("/health")
    def health_check():
        try:
            # THE PUBLIC ANSWER (2026-09-24): whether the service is up, and no
            # more. It used to carry the exact version and the number of
            # containers to any caller on the open internet - the same finding
            # as review D8's cache_directory, and nothing in DDC reads either:
            # the probe in the Dockerfile opens this URL and checks that it
            # does not raise.
            health_data = {
                "status": "healthy",
                "service": "DockerDiscordControl",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            detailed = _caller_is_logged_in()
            if detailed:
                # DDC_VERSION is set by the Dockerfile (single source for the version)
                health_data["version"] = (f"v{os.environ['DDC_VERSION']}"
                                          if os.environ.get("DDC_VERSION") else "unknown")

            try:
                config = load_config()
                server_config_service = get_server_config_service()
                servers = server_config_service.get_all_servers()
                if detailed:
                    health_data["config_loaded"] = True
                    health_data["servers_configured"] = len(servers)

                if config.get("web_ui_password_hash") is None:
                    # Said in public, and only in this state: with no password
                    # set the setup page is open to anybody who loads the
                    # panel, so this describes nothing a visitor cannot see.
                    health_data["first_time_setup_needed"] = True
                    health_data["setup_instructions"] = "Visit /setup for easy web setup, or set DDC_ADMIN_PASSWORD env var"
                    health_data["setup_url"] = "/setup"
                elif detailed:
                    health_data["first_time_setup_needed"] = False
            except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError):
                if detailed:
                    health_data["config_loaded"] = False
                    health_data["servers_configured"] = 0

            # Proxy or Docker? Reported, not failed: a container restart does not
            # bring a dead daemon back (services/docker_service/reachability.py).
            # PUBLIC, unlike the version and the container count: whether DDC can
            # reach Docker at all is what "healthy" means for this service, and
            # v3.0 step 11 exists so that a healthcheck can tell a dead proxy
            # from a dead daemon. That is the operator's first question at 3am
            # and it must not need a password.
            import services.docker_service.reachability as reachability
            host = os.environ.get("DOCKER_HOST") or reachability.DEFAULT_HOST
            health_data["docker"] = reachability.docker_reachability(
                host, proxied=host == f"unix://{reachability.PROXY_SOCKET}")

            return jsonify(health_data), 200
        except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException, json.JSONDecodeError) as e:
            app.logger.error("Health check failed: %s", e, exc_info=True)
            error_data = {
                "status": "error",
                "service": "DockerDiscordControl",
                "error": "Service temporarily unavailable",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            return jsonify(error_data), 500
