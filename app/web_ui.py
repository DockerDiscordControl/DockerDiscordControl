# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Legacy entry point bridging to the modular web app factory."""

from __future__ import annotations

import os
from typing import Mapping, Optional

from app.utils.web_helpers import set_initial_password_from_env
from app.web import create_app as _create_app

__all__ = ["create_app", "app"]


def create_app(test_config: Optional[Mapping[str, object]] = None):
    """Compatibility wrapper that forwards to :func:`app.web.create_app`."""
    return _create_app(test_config)


set_initial_password_from_env()

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("DDC_WEB_PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# No module-level `app = create_app()` on import: run.py and wsgi.py both call the factory
# themselves, and nothing imports this symbol (checked). Building it here created a second,
# unused Flask application on every import - complete with duplicate blueprint registration
# and two blocking Docker pings with a 5s timeout each.
