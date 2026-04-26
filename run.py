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

import threading
import logging
import sys
import os
import time
from waitress import serve
from app.web_ui import create_app
from bot import main as run_bot
from utils.logging_utils import get_module_logger

# Setup logger
logger = get_module_logger("ddc.main")

def start_web_server():
    """Starts the Flask Web UI using Waitress in a separate thread."""
    try:
        logger.info("🚀 Starting Web UI via Waitress on port 9374...")

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

        serve(
            app,
            host="0.0.0.0",
            port=9374,
            threads=threads,
            ident="DDC-Web",
            _quiet=True  # Reduce waitress startup logs
        )
    except Exception as e:
        logger.critical(f"🔥 Web Server failed to start: {e}", exc_info=True)
        # We don't exit here to let the bot keep running if web fails, 
        # but in a single container, this usually means a restart is needed.
        sys.exit(1)

def main():
    """Main execution flow."""
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
