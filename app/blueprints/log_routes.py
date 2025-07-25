# -*- coding: utf-8 -*-
from flask import Blueprint, Response, current_app, request
import docker
import logging
from app.auth import auth 

log_bp = Blueprint('log_bp', __name__)

@log_bp.route('/container_logs/<container_name>')
@auth.login_required
def get_container_logs(container_name):
    logger = current_app.logger
    max_lines = 500  # Limit the number of log lines to return

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