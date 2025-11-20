#!/bin/sh
# Startup script for Web UI
# Note: Web UI must ALWAYS start, regardless of bot token status,
# so users can configure the token via the Web UI interface.

echo "[WebUI] Starting Gunicorn web server on port ${DDC_WEB_PORT:-9374}..."
exec /usr/bin/python3 -m gunicorn -c gunicorn_config.py app.web_ui:app
