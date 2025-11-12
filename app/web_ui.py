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
else:
    app = create_app()
