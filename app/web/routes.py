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
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import Flask, jsonify, request

from app.auth import auth
from services.admin.admin_service import get_admin_service
from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service


def _validate_admin_users(admin_users: List[str]) -> Dict[str, Any]:
    for user_id in admin_users:
        if not user_id.isdigit():
            return {"success": False, "error": f"Invalid user ID: {user_id}"}
    return {"success": True}


def register_routes(app: Flask) -> None:
    """Attach the admin management and health routes."""

    @app.route("/api/admin-users", methods=["GET", "POST"])
    @auth.login_required
    def admin_users():
        admin_service = get_admin_service()

        if request.method == "GET":
            admin_data = admin_service.get_admin_data()
            return jsonify(admin_data)

        try:
            data = request.json or {}
            admin_users = data.get("discord_admin_users", [])
            admin_notes = data.get("admin_notes", {})

            validation = _validate_admin_users(admin_users)
            if not validation.get("success"):
                return jsonify(validation)

            success = admin_service.save_admin_data(admin_users, admin_notes)
            if success:
                return jsonify({"success": True})
            return jsonify({"success": False, "error": "Failed to save admin data"})
        except (RuntimeError) as e:
            # Security: Log detailed error server-side only, return generic message
            app.logger.error("Error saving admin data: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "An internal error occurred while saving admin data"})

    @app.route("/health")
    def health_check():
        try:
            health_data = {
                "status": "healthy",
                "service": "DockerDiscordControl",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": "v1.1.3",
            }

            try:
                config = load_config()
                health_data["config_loaded"] = True
                server_config_service = get_server_config_service()
                servers = server_config_service.get_all_servers()
                health_data["servers_configured"] = len(servers)

                if config.get("web_ui_password_hash") is None:
                    health_data["first_time_setup_needed"] = True
                    health_data["setup_instructions"] = "Visit /setup for easy web setup, or set DDC_ADMIN_PASSWORD env var"
                    health_data["setup_url"] = "/setup"
                else:
                    health_data["first_time_setup_needed"] = False
            except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError):
                health_data["config_loaded"] = False
                health_data["servers_configured"] = 0

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
