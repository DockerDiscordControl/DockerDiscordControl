# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Donation Configuration - Compatibility functions for donation management
"""

from utils.logging_utils import get_module_logger

logger = get_module_logger('donation_config')

def get_donation_disable_key() -> str:
    """Get donation disable key (compatibility function)."""
    try:
        from services.config.config_service import get_config_service
        config_service = get_config_service()
        config = config_service.get_config()
        return config.get('donation_disable_key', '')
    except Exception as e:  # noqa: BLE001 - see set_donation_disable_key below
        logger.error("Donation disable key could not be read: %s: %s",
                     type(e).__name__, e, exc_info=True)
        # Config access errors - return empty string for compatibility
        return ''

def set_donation_disable_key(key: str) -> bool:
    """Set donation disable key (compatibility function)."""
    try:
        from services.config.config_service import get_config_service
        config_service = get_config_service()
        config = config_service.get_config()
        config['donation_disable_key'] = key
        config_service.save_config(config)
        return True
    except Exception as e:  # noqa: BLE001
        # Config access or save errors - the caller still gets False, but say why:
        # this returned it with no log at all (SPEC.md Z8, review A9).
        #
        # Broad since review E13. The tuple that stood here listed seven types
        # and not the one that actually happens: ConfigService.save_config never
        # returns success=False, it raises ConfigSaveError (a DDCBaseException).
        # The single failure these two helpers exist to absorb was the single
        # one they let through, and a function documented to return a bool
        # raised at its caller instead.
        logger.error("Donation disable key could not be saved: %s: %s",
                     type(e).__name__, e, exc_info=True)
        return False
