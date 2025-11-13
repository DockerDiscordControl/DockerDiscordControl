# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
from flask import Blueprint, Response, current_app, request, jsonify
from app.auth import auth

log_bp = Blueprint('log_bp', __name__)

@log_bp.route('/container_logs/<container_name>')
@auth.login_required
def get_container_logs(container_name):
    """Get container logs using ContainerLogService."""
    try:
        # Use ContainerLogService for business logic
        from services.web.container_log_service import get_container_log_service, ContainerLogRequest

        service = get_container_log_service()
        request_obj = ContainerLogRequest(
            container_name=container_name,
            max_lines=500
        )

        # Get logs through service
        result = service.get_container_logs(request_obj)

        if result.success:
            return Response(result.content, mimetype='text/plain')
        else:
            current_app.logger.warning(f"Container log request failed: {result.error}")
            return Response(result.error, status=result.status_code, mimetype='text/plain')

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container_log_service unavailable, service method failures)
        current_app.logger.error(f"Service error in get_container_logs route: {e}", exc_info=True)
        return Response("Service error occurred.", status=500, mimetype='text/plain')
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid request parameters, response processing failures)
        current_app.logger.error(f"Data error in get_container_logs route: {e}", exc_info=True)
        return Response("Data error occurred.", status=500, mimetype='text/plain')

@log_bp.route('/bot_logs')
@auth.login_required
def get_bot_logs():
    """Get bot logs using ContainerLogService."""
    try:
        # Use ContainerLogService for business logic
        from services.web.container_log_service import get_container_log_service, FilteredLogRequest, LogType

        service = get_container_log_service()
        request_obj = FilteredLogRequest(
            log_type=LogType.BOT,
            max_lines=500
        )

        # Get logs through service
        result = service.get_filtered_logs(request_obj)

        if result.success:
            return Response(result.content, mimetype='text/plain')
        else:
            current_app.logger.error(f"Bot log request failed: {result.error}")
            return Response(result.error, status=result.status_code, mimetype='text/plain')

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container_log_service unavailable, service method failures)
        current_app.logger.error(f"Service error in get_bot_logs route: {e}", exc_info=True)
        return Response("Service error fetching bot logs", status=500, mimetype='text/plain')
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid request parameters, response processing failures)
        current_app.logger.error(f"Data error in get_bot_logs route: {e}", exc_info=True)
        return Response("Data error fetching bot logs", status=500, mimetype='text/plain')

@log_bp.route('/discord_logs')
@auth.login_required
def get_discord_logs():
    """Get Discord logs using ContainerLogService."""
    try:
        # Use ContainerLogService for business logic
        from services.web.container_log_service import get_container_log_service, FilteredLogRequest, LogType

        service = get_container_log_service()
        request_obj = FilteredLogRequest(
            log_type=LogType.DISCORD,
            max_lines=500
        )

        # Get logs through service
        result = service.get_filtered_logs(request_obj)

        if result.success:
            return Response(result.content, mimetype='text/plain')
        else:
            current_app.logger.error(f"Discord log request failed: {result.error}")
            return Response(result.error, status=result.status_code, mimetype='text/plain')

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container_log_service unavailable, service method failures)
        current_app.logger.error(f"Service error in get_discord_logs route: {e}", exc_info=True)
        return Response("Service error fetching Discord logs", status=500, mimetype='text/plain')
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid request parameters, response processing failures)
        current_app.logger.error(f"Data error in get_discord_logs route: {e}", exc_info=True)
        return Response("Data error fetching Discord logs", status=500, mimetype='text/plain')

@log_bp.route('/webui_logs')
@auth.login_required
def get_webui_logs():
    """Get Web UI logs using ContainerLogService."""
    try:
        # Use ContainerLogService for business logic
        from services.web.container_log_service import get_container_log_service, FilteredLogRequest, LogType

        service = get_container_log_service()
        request_obj = FilteredLogRequest(
            log_type=LogType.WEBUI,
            max_lines=500
        )

        # Get logs through service
        result = service.get_filtered_logs(request_obj)

        if result.success:
            return Response(result.content, mimetype='text/plain')
        else:
            current_app.logger.error(f"Web UI log request failed: {result.error}")
            return Response(result.error, status=result.status_code, mimetype='text/plain')

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container_log_service unavailable, service method failures)
        current_app.logger.error(f"Service error in get_webui_logs route: {e}", exc_info=True)
        return Response("Service error fetching Web UI logs", status=500, mimetype='text/plain')
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid request parameters, response processing failures)
        current_app.logger.error(f"Data error in get_webui_logs route: {e}", exc_info=True)
        return Response("Data error fetching Web UI logs", status=500, mimetype='text/plain')

@log_bp.route('/application_logs')
@auth.login_required
def get_application_logs():
    """Get application logs using ContainerLogService."""
    try:
        # Use ContainerLogService for business logic
        from services.web.container_log_service import get_container_log_service, FilteredLogRequest, LogType

        service = get_container_log_service()
        request_obj = FilteredLogRequest(
            log_type=LogType.APPLICATION,
            max_lines=500
        )

        # Get logs through service
        result = service.get_filtered_logs(request_obj)

        if result.success:
            return Response(result.content, mimetype='text/plain')
        else:
            current_app.logger.error(f"Application log request failed: {result.error}")
            return Response(result.error, status=result.status_code, mimetype='text/plain')

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container_log_service unavailable, service method failures)
        current_app.logger.error(f"Service error in get_application_logs route: {e}", exc_info=True)
        return Response("Service error fetching application logs", status=500, mimetype='text/plain')
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid request parameters, response processing failures)
        current_app.logger.error(f"Data error in get_application_logs route: {e}", exc_info=True)
        return Response("Data error fetching application logs", status=500, mimetype='text/plain')

@log_bp.route('/action_logs')
@auth.login_required
def get_action_logs():
    """Get action logs using ContainerLogService."""
    try:
        # Use ContainerLogService for business logic
        from services.web.container_log_service import get_container_log_service, ActionLogRequest

        service = get_container_log_service()
        request_obj = ActionLogRequest(
            format_type="text",
            limit=500
        )

        # Get logs through service
        result = service.get_action_logs(request_obj)

        if result.success:
            return Response(result.content, mimetype='text/plain')
        else:
            current_app.logger.error(f"Action log request failed: {result.error}")
            return Response(result.error, status=result.status_code, mimetype='text/plain')

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container_log_service unavailable, service method failures)
        current_app.logger.error(f"Service error in get_action_logs route: {e}", exc_info=True)
        return Response("Service error fetching action logs", status=500, mimetype='text/plain')
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid request parameters, response processing failures)
        current_app.logger.error(f"Data error in get_action_logs route: {e}", exc_info=True)
        return Response("Data error fetching action logs", status=500, mimetype='text/plain')

@log_bp.route('/action_logs_json')
@auth.login_required
def get_action_logs_json():
    """Get action logs as JSON using ContainerLogService."""
    try:
        # Use ContainerLogService for business logic
        from services.web.container_log_service import get_container_log_service, ActionLogRequest

        service = get_container_log_service()
        request_obj = ActionLogRequest(
            format_type="json",
            limit=500
        )

        # Get logs through service
        result = service.get_action_logs(request_obj)

        if result.success:
            return jsonify(result.data)
        else:
            current_app.logger.error(f"Action log JSON request failed: {result.error}")
            return jsonify({'success': False, 'error': result.error}), result.status_code

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container_log_service unavailable, service method failures)
        current_app.logger.error(f"Service error in get_action_logs_json route: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Service error occurred'}), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid request parameters, response processing failures, JSON serialization)
        current_app.logger.error(f"Data error in get_action_logs_json route: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Data error occurred'}), 500

@log_bp.route('/clear_logs', methods=['POST'])
@auth.login_required
def clear_logs():
    """Clear logs using ContainerLogService."""
    try:
        # Use ContainerLogService for business logic
        from services.web.container_log_service import get_container_log_service, ClearLogRequest

        log_type = request.json.get('log_type', 'container') if request.json else 'container'

        service = get_container_log_service()
        request_obj = ClearLogRequest(log_type=log_type)

        # Clear logs through service
        result = service.clear_logs(request_obj)

        if result.success:
            return jsonify(result.data)
        else:
            current_app.logger.error(f"Clear logs request failed: {result.error}")
            return jsonify({'success': False, 'message': result.error}), result.status_code

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (container_log_service unavailable, service method failures)
        current_app.logger.error(f"Service error in clear_logs route: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Service error occurred'}), 500
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid request parameters, response processing failures, JSON parsing)
        current_app.logger.error(f"Data error in clear_logs route: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Data error occurred'}), 500 