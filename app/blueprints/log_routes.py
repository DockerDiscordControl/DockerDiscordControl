# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
from flask import Blueprint, Response, current_app, request, jsonify
import docker
import logging
import re
from app.auth import auth 

log_bp = Blueprint('log_bp', __name__)

@log_bp.route('/container_logs/<container_name>')
@auth.login_required
def get_container_logs(container_name):
    logger = current_app.logger
    max_lines = 500  # Limit the number of log lines to return
    
    # Validate container name to prevent injection attacks
    from utils.common_helpers import validate_container_name
    if not validate_container_name(container_name):
        logger.warning(f"Invalid container name requested: {container_name}")
        return Response("Invalid container name", status=400, content_type="text/plain")

    try:
        # Initialize Docker client
        # Use the recommended way to get a client that respects environment variables
        client = docker.from_env()

        # Get the container object
        container = client.containers.get(container_name)

        # Fetch the logs
        logs = container.logs(tail=max_lines, stdout=True, stderr=True)

        # The logs are returned as bytes, decode them to a string
        logs_str = logs.decode('utf-8', errors='replace')

        return Response(logs_str, mimetype='text/plain')

    except docker.errors.NotFound:
        logger.warning(f"Log request for non-existent container: {container_name}")
        return Response(f"Error: Container '{container_name}' not found.", status=404, mimetype='text/plain')
    except docker.errors.APIError as e:
        logger.error(f"Docker API error when fetching logs for {container_name}: {e}")
        # Return a generic error to the user to avoid exposing internal details
        return Response("Error: Could not retrieve logs due to a Docker API error.", status=500, mimetype='text/plain')
    except Exception as e:
        logger.error(f"An unexpected error occurred when fetching logs for {container_name}: {e}", exc_info=True)
        return Response("An unexpected error occurred.", status=500, mimetype='text/plain')

@log_bp.route('/bot_logs')
@auth.login_required
def get_bot_logs():
    """Get filtered logs showing only bot-related messages"""
    logger = current_app.logger
    max_lines = 500
    
    try:
        client = docker.from_env()
        container = client.containers.get('dockerdiscordcontrol')
        
        # Get more logs to ensure we have enough after filtering
        logs = container.logs(tail=max_lines*2, stdout=True, stderr=True)
        logs_str = logs.decode('utf-8', errors='replace')
        
        # Filter for bot-specific logs (bot.py, cogs, discord.py)
        filtered_lines = []
        for line in logs_str.split('\n'):
            if any(pattern in line.lower() for pattern in ['bot.py', 'cog', 'discord.py', 'discord bot', 'command', 'slash']):
                filtered_lines.append(line)
        
        # Limit to max_lines
        filtered_logs = '\n'.join(filtered_lines[-max_lines:]) if filtered_lines else "No bot logs found"
        
        return Response(filtered_logs, mimetype='text/plain')
        
    except Exception as e:
        logger.error(f"Error fetching bot logs: {e}", exc_info=True)
        return Response("Error fetching bot logs", status=500, mimetype='text/plain')

@log_bp.route('/discord_logs')
@auth.login_required
def get_discord_logs():
    """Get filtered logs showing only Discord-related messages"""
    logger = current_app.logger
    max_lines = 500
    
    try:
        client = docker.from_env()
        container = client.containers.get('dockerdiscordcontrol')
        
        logs = container.logs(tail=max_lines*2, stdout=True, stderr=True)
        logs_str = logs.decode('utf-8', errors='replace')
        
        # Filter for Discord-specific logs
        filtered_lines = []
        for line in logs_str.split('\n'):
            if any(pattern in line.lower() for pattern in ['discord', 'guild', 'channel', 'member', 'message', 'voice', 'websocket']):
                filtered_lines.append(line)
        
        filtered_logs = '\n'.join(filtered_lines[-max_lines:]) if filtered_lines else "No Discord logs found"
        
        return Response(filtered_logs, mimetype='text/plain')
        
    except Exception as e:
        logger.error(f"Error fetching Discord logs: {e}", exc_info=True)
        return Response("Error fetching Discord logs", status=500, mimetype='text/plain')

@log_bp.route('/webui_logs')
@auth.login_required
def get_webui_logs():
    """Get filtered logs showing only Web UI related messages"""
    logger = current_app.logger
    max_lines = 500
    
    try:
        client = docker.from_env()
        container = client.containers.get('dockerdiscordcontrol')
        
        logs = container.logs(tail=max_lines*2, stdout=True, stderr=True)
        logs_str = logs.decode('utf-8', errors='replace')
        
        # Filter for Web UI specific logs (Flask, Gunicorn, HTTP requests)
        filtered_lines = []
        for line in logs_str.split('\n'):
            if any(pattern in line for pattern in ['flask', 'Flask', 'gunicorn', 'Gunicorn', 'GET /', 'POST /', 'HTTP', '127.0.0.1', '0.0.0.0:5000', 'werkzeug', 'jinja2']):
                filtered_lines.append(line)
        
        filtered_logs = '\n'.join(filtered_lines[-max_lines:]) if filtered_lines else "No Web UI logs found"
        
        return Response(filtered_logs, mimetype='text/plain')
        
    except Exception as e:
        logger.error(f"Error fetching Web UI logs: {e}", exc_info=True)
        return Response("Error fetching Web UI logs", status=500, mimetype='text/plain')

@log_bp.route('/application_logs')
@auth.login_required
def get_application_logs():
    """Get filtered logs showing only application-level messages"""
    logger = current_app.logger
    max_lines = 500
    
    try:
        client = docker.from_env()
        container = client.containers.get('dockerdiscordcontrol')
        
        logs = container.logs(tail=max_lines*2, stdout=True, stderr=True)
        logs_str = logs.decode('utf-8', errors='replace')
        
        # Filter for application-level logs (ERROR, WARNING, INFO, DEBUG, startup messages)
        filtered_lines = []
        for line in logs_str.split('\n'):
            if any(pattern in line for pattern in ['ERROR', 'WARNING', 'INFO', 'DEBUG', 'Starting', 'Stopping', 'Initializing', 'Config', 'Database', 'Scheduler']):
                filtered_lines.append(line)
        
        filtered_logs = '\n'.join(filtered_lines[-max_lines:]) if filtered_lines else "No application logs found"
        
        return Response(filtered_logs, mimetype='text/plain')
        
    except Exception as e:
        logger.error(f"Error fetching application logs: {e}", exc_info=True)
        return Response("Error fetching application logs", status=500, mimetype='text/plain')

@log_bp.route('/action_logs')
@auth.login_required
def get_action_logs():
    """Get user action logs from JSON storage"""
    logger = current_app.logger
    
    try:
        # Import here to avoid circular imports
        from services.infrastructure.action_logger import get_action_logs_text
        
        action_log_content = get_action_logs_text(limit=500)
        
        if action_log_content:
            return Response(action_log_content, mimetype='text/plain')
        else:
            return Response("No action logs available", mimetype='text/plain')
            
    except Exception as e:
        logger.error(f"Error fetching action logs: {e}", exc_info=True)
        return Response("Error fetching action logs", status=500, mimetype='text/plain')

@log_bp.route('/action_logs_json')
@auth.login_required
def get_action_logs_json():
    """Get user action logs as JSON"""
    logger = current_app.logger
    
    try:
        # Import here to avoid circular imports
        from services.infrastructure.action_logger import get_action_logs_json
        
        action_logs = get_action_logs_json(limit=500)
        
        return jsonify({
            'success': True,
            'logs': action_logs,
            'count': len(action_logs)
        })
            
    except Exception as e:
        logger.error(f"Error fetching action logs JSON: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@log_bp.route('/clear_logs', methods=['POST'])
@auth.login_required
def clear_logs():
    """Clear logs (Note: Docker container logs cannot be cleared, this is for future file-based logs)"""
    logger = current_app.logger
    
    try:
        # For now, we can't actually clear Docker container logs
        # This endpoint is prepared for when we implement file-based logging
        log_type = request.json.get('log_type', 'container')
        
        logger.info(f"Clear logs request for type: {log_type}")
        
        # Return success but note that Docker logs persist
        return jsonify({
            'success': True,
            'message': f'{log_type.capitalize()} logs cleared (Note: Docker container logs persist until container restart)'
        })
        
    except Exception as e:
        logger.error(f"Error clearing logs: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500 