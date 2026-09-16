#!/bin/sh
# Startup script for Web UI
# Note: Web UI must ALWAYS start, regardless of bot token status,
# so users can configure the token via the Web UI interface.

echo "[WebUI] Starting Gunicorn web server on port ${DDC_WEB_PORT:-9374}..."
# Development only. This does NOT work in the production image: gunicorn is not installed there
# (production uses waitress, started from run.py via the entrypoint) and gunicorn_config.py does
# not exist in the repository either. Kept as a dev convenience; the factory form is used because
# app.web_ui no longer builds a module-level app on import.
exec /usr/bin/python3 -m gunicorn -c gunicorn_config.py "app.web_ui:create_app()"
