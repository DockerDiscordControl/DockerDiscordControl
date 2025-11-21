#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - WSGI Entry Point                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
WSGI entry point for DockerDiscordControl
Provides proper WSGI application for Gunicorn
"""

import sys
import os

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the Flask app factory
from app.web_ui import create_app  # pylint: disable=wrong-import-position

# Create WSGI application
application = create_app()

# For development server
if __name__ == '__main__':
    application.run(host='0.0.0.0', port=5001, debug=False)
