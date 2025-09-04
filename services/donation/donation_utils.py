# -*- coding: utf-8 -*-
"""
Donation Utils - Minimal compatibility functions
Now primarily uses MechService, these are compatibility functions.
"""

def is_donations_disabled() -> bool:
    """Check if donations are disabled by premium key (compatibility function)."""
    try:
        from services.config.config_service import get_config_service
        config_service = get_config_service()
        config = config_service.get_config()
        return bool(config.get('donation_disable_key'))
    except:
        return False

def validate_donation_key(key: str) -> bool:
    """Validate donation key (compatibility function)."""
    try:
        from services.config.config_service import get_config_service
        config_service = get_config_service()
        return config_service.validate_donation_key(key)
    except:
        return False