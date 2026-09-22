# -*- coding: utf-8 -*-
"""Setup step: the web panel's second factor (see app/blueprints/two_factor_routes.py)."""

from __future__ import annotations

from app.blueprints.two_factor_routes import install_two_factor

__all__ = ["install_two_factor"]
