# -*- coding: utf-8 -*-
from flask import (
    Blueprint, Response, current_app, send_file, jsonify, flash, redirect, url_for, session, request
)
from datetime import datetime, timezone # For clear_action_log timestamp
import time
from app.auth import auth

# Import the rate limiting decorator from log_routes.py
try:
    from app.blueprints.log_routes import rate_limit
except ImportError:
    # Fallback: Own rate limit implementation if import fails
    from functools import wraps
    # Simple rate limiting for log requests
    _last_log_request = {}  # IP -> timestamp
    _min_request_interval = 60.0  # Increased to 60 seconds to match client-side auto-refresh interval
    
    def rate_limit(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get client IP (simplified)
            client_ip = request.remote_addr if 'request' in globals() else 'unknown'
            
            # Check if the last request from this IP was too recent
            current_time = time.time()
            if client_ip in _last_log_request:
                elapsed = current_time - _last_log_request[client_ip]
                if elapsed < _min_request_interval:
                    return Response(
                        "TOO MANY REQUESTS: Please wait before requesting logs again.", 
                        status=429, 
                        mimetype='text/plain'
                    )
            
            # Update the timestamp of the last request
            _last_log_request[client_ip] = current_time
            
            return f(*args, **kwargs)
        return decorated_function

# Import the central ACTION_LOG_FILE constant and log_user_action function
try:
    from services.infrastructure.action_logger import log_user_action, _ACTION_LOG_FILE as ACTION_LOG_FILE
except ImportError:
    # Fallback for tests or when the central version is not available
    from app.utils.web_helpers import ACTION_LOG_FILE, log_user_action

action_log_bp = Blueprint('action_log_bp', __name__)

@action_log_bp.route('/action-log')
@auth.login_required
@rate_limit
def get_action_log():
    logger = current_app.logger
    try:
        with open(ACTION_LOG_FILE, 'r', encoding='utf-8') as f:
            log_content = f.read()
    except FileNotFoundError:
        log_content = "Action log file not found."
        logger.error(f"Action log file ({ACTION_LOG_FILE}) not found for /action-log endpoint.")
    except Exception as e:
        log_content = "Error reading action log. Please check the logs for details."
        logger.error(f"Error reading action log ({ACTION_LOG_FILE}): {str(e)}", exc_info=True)
    return Response(log_content, mimetype='text/plain')

@action_log_bp.route('/download-action-log')
@auth.login_required
def download_action_log():
    try:
        return send_file(ACTION_LOG_FILE, as_attachment=True, download_name='user_actions.log')
    except FileNotFoundError:
        flash('Action log file not found. Cannot download.', 'error')
        # Redirect to a relevant page, e.g., the main config page or a dedicated logs page
        # Assuming 'main_bp.config_page' is the route for '/'. Adjust if namespace/name is different after BP registration.
        return redirect(url_for('main_bp.config_page')) 

@action_log_bp.route('/clear-action-log', methods=['POST'])
@auth.login_required
def clear_action_log():
    logger = current_app.logger
    try:
        user = session.get('user', 'Unknown User') # Get user from session for logging
        with open(ACTION_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} - Log cleared by user: {user}\n")
        log_user_action("CLEAR", "Action Log", source="Web UI Blueprint", details=f"Cleared by {user}")
        logger.info(f"Action log cleared successfully by user: {user}.")
        flash('Action log cleared successfully.', 'success')
        return jsonify({'success': True, 'message': 'Action log cleared successfully.'})
    except Exception as e:
        logger.error(f"Error clearing action log: {str(e)}", exc_info=True)
        flash('Error clearing action log. Please check the logs for details.', 'error')
        return jsonify({'success': False, 'message': 'Error clearing action log. Please check the logs for details.'}) 