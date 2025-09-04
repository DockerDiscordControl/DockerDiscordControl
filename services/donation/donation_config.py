# -*- coding: utf-8 -*-
"""
Donation Configuration - Compatibility functions for donation management
"""

def get_donation_disable_key() -> str:
    """Get donation disable key (compatibility function)."""
    try:
        from services.config.config_service import get_config_service
        config_service = get_config_service()
        config = config_service.get_config()
        return config.get('donation_disable_key', '')
    except:
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
    except:
        return False