# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Donation Utils - Minimal compatibility functions
Now primarily uses MechService, these are compatibility functions.
"""

def is_donations_disabled() -> bool:
    """Check if donations are disabled by premium key (compatibility function)."""
    try:
        # SERVICE FIRST: Use Request/Result pattern for config access
        from services.config.config_service import get_config_service, GetConfigRequest
        config_service = get_config_service()
        config_request = GetConfigRequest(force_reload=False)
        config_result = config_service.get_config_service(config_request)

        if config_result.success:
            return bool(config_result.config.get('donation_disable_key'))
        else:
            return False
    except (ValueError, TypeError, AttributeError, RuntimeError) as e:
        # Service or data access errors - return False for compatibility
        return False

def validate_donation_key(key: str) -> bool:
    """Validate donation key (compatibility function)."""
    try:
        # SERVICE FIRST: Use Request/Result pattern for donation key validation
        from services.config.config_service import get_config_service, ValidateDonationKeyRequest
        config_service = get_config_service()
        validation_request = ValidateDonationKeyRequest(key=key)
        validation_result = config_service.validate_donation_key_service(validation_request)

        if validation_result.success:
            return validation_result.is_valid
        else:
            return False
    except (ValueError, TypeError, AttributeError, RuntimeError) as e:
        # Service or validation errors - return False for compatibility
        return False
