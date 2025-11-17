# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Donation Services - DDC donation system functionality
Now primarily uses MechService for donation management.
"""

# Only keep the donation management service for Web UI modal and compatibility functions
from .donation_management_service import get_donation_management_service
from .donation_utils import is_donations_disabled, validate_donation_key
from .donation_config import get_donation_disable_key, set_donation_disable_key

__all__ = [
    'get_donation_management_service',
    'is_donations_disabled',
    'validate_donation_key',
    'get_donation_disable_key',
    'set_donation_disable_key'
]