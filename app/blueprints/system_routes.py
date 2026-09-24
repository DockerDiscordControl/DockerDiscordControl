# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Actions DDC performs on ITSELF, rather than on the containers it watches.

There is one so far: restarting its own container. It lives here and not in
main_routes.py for two reasons. The small one is that main_routes.py was ten
lines under the 1500-line ceiling the suite enforces, and this route put it
over - the ceiling doing its job. The larger one is that "act on DDC" is not
the same subject as "serve the settings page", and a file that already holds
sixty routes is where subjects go to be lost.
"""

from flask import Blueprint, current_app, jsonify

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
