# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Config Services Package - Unified configuration service
"""

from .config_service import get_config_service, ConfigService, ConfigServiceResult

__all__ = [
    'get_config_service', 'ConfigService', 'ConfigServiceResult'
]
