# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Save the whole configuration as one file, and restore it (operator, 2026-09-26).

The file holds the bot token, the second factor's secret and the password
hash, and it is not encrypted (operator decision): so every one of these asks
for the panel password AGAIN - a session left open on somebody's laptop is not
enough to walk off with the installation, or to replace it. The attempts share
one brake per address, like the second factor's codes.

A restore is two steps: the upload is checked and described (preview), and
only a second request with the password applies it. The configuration it
replaces is kept (services/config/backup_service.py), and DDC restarts, since
every service has read its configuration into memory.
"""

from __future__ import annotations

import os
import time

from flask import Blueprint, Response, current_app, jsonify, request

from app.auth import SimpleRateLimiter, auth, session_user, verify_password
from services.infrastructure.action_logger import log_user_action

backup_bp = Blueprint("backup_bp", __name__)

# Five password attempts per minute and address across the three routes.
backup_limiter = SimpleRateLimiter(limit=5, per_seconds=60)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _config_dir():
    from utils.config_paths import get_config_dir

    return get_config_dir()


def _version() -> str:
    return (os.environ.get("DDC_VERSION") or "").strip()


def _password_refused():
    """None when the request carries the right password again, else the answer."""
    if backup_limiter.is_rate_limited(request.remote_addr):
        current_app.logger.warning(f"Backup/restore password attempts rate-limited from {request.remote_addr}")
        return jsonify({"success": False, "error": "rate_limited"}), 429
    user = session_user() or auth.current_user()
    if not user or not verify_password(user, request.form.get("password", "")):
        current_app.logger.warning(f"Backup/restore refused: wrong password from {request.remote_addr}")
        return jsonify({"success": False, "error": "wrong_password"}), 403
    return None


@backup_bp.route("/api/config/backup", methods=["POST"])
@auth.login_required
def download_backup():
    refused = _password_refused()
    if refused:
        return refused
    from services.config.backup_service import create_backup

    data = create_backup(_config_dir(), _version())
    log_user_action("BACKUP", "configuration", source="Web UI backup")
    name = time.strftime("ddc-backup-%Y%m%d-%H%M%S.zip")
    return Response(data, mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store",
    })


@backup_bp.route("/api/config/restore/preview", methods=["POST"])
@auth.login_required
def preview_restore():
    """Check the upload and say what it holds. Changes nothing but a pending file."""
    refused = _password_refused()
    if refused:
        return refused
    from services.config.backup_service import PENDING, BackupRefused, inspect_backup

    upload = request.files.get("backup")
    if upload is None:
        return jsonify({"success": False, "error": "no_file"}), 400
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    try:
        inspected = inspect_backup(data)
    except BackupRefused as refusal:
        return jsonify({"success": False, "error": "refused", "reason": str(refusal)}), 400
    pending = _config_dir() / PENDING
    pending.write_bytes(data)
    pending.chmod(0o600)
    manifest = inspected.manifest
    return jsonify({"success": True, "created_at": manifest.get("created_at", ""),
                    "ddc_version": manifest.get("ddc_version", ""),
                    "summary": manifest.get("summary", {}),
                    "current_version": _version()})


@backup_bp.route("/api/config/restore/apply", methods=["POST"])
@auth.login_required
def apply_restore():
    """Replace the configuration with the previewed backup, then restart DDC."""
    refused = _password_refused()
    if refused:
        return refused
    from services.config.backup_service import PENDING, BackupRefused, restore_backup

    pending = _config_dir() / PENDING
    if not pending.exists():
        return jsonify({"success": False, "error": "nothing_pending"}), 400
    try:
        kept = restore_backup(_config_dir(), pending.read_bytes(), _version())
    except BackupRefused as refusal:
        return jsonify({"success": False, "error": "refused", "reason": str(refusal)}), 400
    finally:
        pending.unlink(missing_ok=True)
    log_user_action("RESTORE", "configuration", source=f"Web UI restore (previous kept as {kept.name})")
    from services.docker_service.self_restart import restart_myself

    started, name = restart_myself()
    return jsonify({"success": True, "kept": kept.name, "restarting": bool(started)})
