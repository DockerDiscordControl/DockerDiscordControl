# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                      #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Single Entry Point for DockerDiscordControl (DDC).
Starts both the Web UI (via Waitress) and the Discord Bot in a single process.
"""

import errno
import threading
import logging
import sys
import os
import time
from waitress import serve
from app.bootstrap.runtime import get_web_port
from app.web_ui import create_app
from bot import main as run_bot, install_sigterm_handler
from utils.logging_utils import get_module_logger

# Setup logger
logger = get_module_logger("ddc.main")

# A port that is still in use (host network, previous instance shutting down) gets
# a few more bind attempts before the process gives up.
WEB_BIND_ATTEMPTS = 5
WEB_BIND_RETRY_DELAY = 3


def _terminate_process(exit_code: int) -> None:
    """Exit the whole process immediately, whichever thread calls this."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(exit_code)


def _serve_web(app, port, threads):
    """Serve the web UI with the server the TLS mode needs (app/web/tls.py).

    waitress for plain HTTP and behind a TLS proxy; werkzeug's threaded TLS
    server for DDC_TLS_MODE=self-signed, since waitress cannot terminate TLS.
    """
    from app.web.tls import tls_mode

    if tls_mode(os.environ) == "self-signed":
        from pathlib import Path

        import app.web.tls as tls
        from utils.config_paths import get_config_dir

        tls_directory = Path(get_config_dir()) / "tls"
        certificate = tls.ensure_self_signed_certificate(tls_directory)
        # The third place an address can be learned, and the only one that
        # sees a bookmark on https://<ip>: a bare address sends no SNI and
        # never passes the redirect (app/web/tls.py).
        tls.learn_from_requests(app, tls_directory)
        logger.info(
            f"🔒 HTTPS with a self-signed certificate ({'new' if certificate.created else 'kept'}, "
            f"valid until {certificate.not_after:%Y-%m-%d}). Trust step: compare the browser's "
            f"SHA-256 fingerprint with {certificate.fingerprint}"
        )
        tls.make_tls_server(app, "0.0.0.0", port, certificate).serve_forever()
        return
    serve(
        app,
        host="0.0.0.0",
        port=port,
        threads=threads,
        ident="DDC-Web",
        _quiet=True  # Reduce waitress startup logs
    )


def start_web_server():
    """Starts the Flask Web UI using Waitress in a separate thread."""
    try:
        port = get_web_port()
        logger.info(f"🚀 Starting Web UI via Waitress on port {port}...")

        # Create Flask app
        app = create_app()

        # Scale waitress thread pool to host CPUs (clamped 4..8) so concurrent
        # requests don't queue behind a fixed 4-thread pool. Override possible
        # via DDC_WAITRESS_THREADS for tuning on small/large hosts.
        cpu_count = os.cpu_count() or 4
        try:
            threads = int(os.environ.get("DDC_WAITRESS_THREADS", "0")) or max(4, min(8, cpu_count))
        except (TypeError, ValueError):
            threads = max(4, min(8, cpu_count))
        threads = max(2, min(16, threads))
        logger.info(f"Waitress thread pool size: {threads} (cpu_count={cpu_count})")

        for attempt in range(1, WEB_BIND_ATTEMPTS + 1):
            try:
                _serve_web(app, port, threads)
                break
            except OSError as e:
                if e.errno != errno.EADDRINUSE:
                    raise
                if attempt == WEB_BIND_ATTEMPTS:
                    logger.critical(
                        f"🔥 Port {port} is already in use. With host networking set DDC_WEB_PORT "
                        f"to a free port; with bridge networking change the host port mapping."
                    )
                    raise
                logger.warning(
                    f"Port {port} is already in use (attempt {attempt}/{WEB_BIND_ATTEMPTS}) - "
                    f"retrying in {WEB_BIND_RETRY_DELAY} s..."
                )
                time.sleep(WEB_BIND_RETRY_DELAY)
        logger.critical("🔥 Web Server stopped unexpectedly")
    except Exception as e:
        logger.critical(f"🔥 Web Server failed to start: {e}", exc_info=True)

    # sys.exit() here would only end this daemon thread and leave the container
    # "Up" without a web UI (the only place to fix the configuration). Terminate
    # the whole process instead so Docker's restart policy restarts the container.
    logger.critical("💀 Web UI is not running - terminating DDC so the container gets restarted")
    _terminate_process(1)

def main():
    """Main execution flow."""
    # run.py is PID 1 in the container: without a handler SIGTERM is ignored and
    # `docker stop` waits 10 s before killing. py-cord installs its own handler
    # once bot.run() starts.
    install_sigterm_handler(logger)

    logger.info("==================================================")
    logger.info("   DockerDiscordControl (DDC) - Startup Sequence   ")
    logger.info("==================================================")

    # 1. Start Web Server (Daemon Thread)
    # Daemon means it will be killed automatically when the main thread (Bot) exits
    web_thread = threading.Thread(target=start_web_server, daemon=True, name="Web-UI")
    web_thread.start()

    # Give web server a moment to initialize logging/resources
    time.sleep(1)

    # 2. Start Discord Bot (Main Thread)
    # py-cord handles signals (SIGINT/SIGTERM) well in the main thread
    logger.info("🤖 Starting Discord Bot...")
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("🛑 Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.critical(f"💀 Bot crashed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
