# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech System Services - Consolidated mech evolution and animation functionality
"""

# Import main services for easy access
from .mech_service import get_mech_service, MechServiceAdapter
from .mech_evolutions import get_evolution_level, get_evolution_info, get_evolution_level_info, get_evolution_config_service
from .mech_state_manager import MechStateManager

# Backward compatibility alias
MechService = MechServiceAdapter

__all__ = [
    'get_mech_service',
    'MechService',
    'MechServiceAdapter',
    'get_evolution_level',
    'get_evolution_info',
    'get_evolution_level_info',
    'get_evolution_config_service',
    'MechStateManager'
]
