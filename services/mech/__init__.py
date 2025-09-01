# -*- coding: utf-8 -*-
"""
Mech System Services - Consolidated mech evolution and animation functionality
"""

# Import main services for easy access
from .mech_service import get_mech_service, MechService
from .mech_animation_service import get_mech_animation_service, MechAnimationService
from .mech_evolutions import EVOLUTION_THRESHOLDS, EVOLUTION_NAMES, get_evolution_level
from .mech_state_manager import MechStateManager

__all__ = [
    'get_mech_service',
    'MechService', 
    'get_mech_animation_service',
    'MechAnimationService',
    'EVOLUTION_THRESHOLDS',
    'EVOLUTION_NAMES',
    'get_evolution_level',
    'MechStateManager'
]