#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Mech Service                                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Mech Service - Re-exports the adapter for backward compatibility

This module now uses the new event-sourced progress_service internally
while maintaining the old API for existing code.
"""

# Re-export everything from the adapter
from .mech_service_adapter import (
    MechServiceAdapter,
    MechState,
    GetMechStateRequest,
    MechStateServiceResult,
    get_mech_service
)

__all__ = [
    'MechServiceAdapter',
    'MechState',
    'GetMechStateRequest',
    'MechStateServiceResult',
    'get_mech_service'
]
