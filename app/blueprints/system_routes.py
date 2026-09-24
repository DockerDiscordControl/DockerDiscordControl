# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Actions DDC performs on ITSELF, rather than on the containers it watches.

Two so far: restarting its own container, and switching its own log level. It lives here and not in
main_routes.py for two reasons. The small one is that main_routes.py was ten
lines under the 1500-line ceiling the suite enforces, and this route put it
over - the ceiling doing its job. The larger one is that "act on DDC" is not
the same subject as "serve the settings page", and a file that already holds
sixty routes is where subjects go to be lost.
"""

from flask import Blueprint, current_app, jsonify, request

from app.auth import auth
from services.infrastructure.action_logger import log_user_action

system_bp = Blueprint('system_bp', __name__)


@system_bp.route('/api/restart-self', methods=['POST'])
@auth.login_required
def restart_self():
    """Restart DDC's own container, at the operator's request.

    Why this is possible at all - an earlier answer to the operator was that it
    was not, "because the systems are separated" - and why the response has to
    leave before the restart: services/docker_service/self_restart.py.

    POST and login_required, because it takes the bot offline: not something a
    passer-by, or a link somebody was sent, may do.
    """
    try:
        from services.docker_service.self_restart import restart_myself

        started, name = restart_myself()
        if not started:
            current_app.logger.error(f"Self-restart refused: {name}")
            return jsonify({'success': False,
                            'error': "Unable to identify DDC's own container"}), 500
        log_user_action("RESTART", name, source="Web UI restart button")
        return jsonify({'success': True, 'container': name})
    except (ImportError, AttributeError, RuntimeError) as e:
        current_app.logger.error(f"Service error restarting own container: {e}",
                                 exc_info=True)
        return jsonify({'success': False, 'error': 'Service error: unable to restart'}), 500


def _config_service():
    """Seam: the configuration store, as one call the tests can replace."""
    from services.config.config_service import get_config_service

    return get_config_service()


def _apply_debug_level(enabled: bool) -> None:
    """Seam: make the running process log that way, now."""
    from utils.logging_utils import refresh_debug_status

    refresh_debug_status()


@system_bp.route('/api/debug-level', methods=['POST'])
@auth.login_required
def set_debug_level():
    """Store the debug level and apply it, without the settings form.

    IT IS A CONTROL, NOT A SETTINGS FIELD (operator, 2026-09-24). The rest of
    that form is one act - a token, a channel list and a language are changed
    together and written together, which is what the Save button is for. This
    has one bit of state, belongs to the log view beside it, and takes effect
    the moment it is stored; making the operator find the Save button on
    another tab for it is asking him to do the page's work.

    STORED AND APPLIED, in that order. Storing without applying is what the
    "restart required" note used to cover for.

    A body without the field is refused rather than read as "off": a request
    that says nothing has not asked for anything.
    """
    body = request.get_json(silent=True) or {}
    if 'enabled' not in body:
        return jsonify({'success': False, 'error': 'No level given'}), 400
    wanted = bool(body['enabled'])
    try:
        service = _config_service()
        config = dict(service.get_config(force_reload=True) or {})
        config['debug_level_enabled'] = wanted
        result = service.save_config(config)
        if not getattr(result, 'success', False):
            current_app.logger.error(f"Could not store the debug level: "
                                     f"{getattr(result, 'message', '')}")
            return jsonify({'success': False, 'error': 'Could not store the level'}), 500
        _apply_debug_level(wanted)
        log_user_action("DEBUG_LEVEL", 'DEBUG' if wanted else 'INFO', source="Web UI log view")
        return jsonify({'success': True, 'enabled': wanted})
    except (ImportError, AttributeError, RuntimeError, OSError, ValueError) as e:
        current_app.logger.error(f"Service error setting the debug level: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error'}), 500
