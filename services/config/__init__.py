# -*- coding: utf-8 -*-
"""
Config Services Package - Unified configuration service
"""

from .config_service import get_config_service, ConfigService, ConfigServiceResult

__all__ = [
    'get_config_service', 'ConfigService', 'ConfigServiceResult'
]