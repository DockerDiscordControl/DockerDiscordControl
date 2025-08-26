# -*- coding: utf-8 -*-
"""
Donation system utilities for checking if donations are disabled via key.
"""

import re
from typing import Optional
from utils.config_loader import load_config


def is_donations_disabled() -> bool:
    """
    Check if donations are disabled by a valid key.
    
    Returns:
        bool: True if donations should be hidden, False otherwise
    """
    try:
        config = load_config()
        donation_key = config.get('donation_disable_key', '').strip()
        
        if not donation_key:
            return False
            
        return validate_donation_key(donation_key)
    except Exception:
        return False


def validate_donation_key(key: str) -> bool:
    """
    Validate a donation disable key.
    
    Args:
        key: The key to validate (fixed key for Buy me a coffee)
        
    Returns:
        bool: True if key is valid, False otherwise
    """
    if not key:
        return False
    
    # Fixed key that can be purchased at Buy me a coffee
    VALID_KEYS = [
        "DDC-DISABLE-2025-PREMIUM",
        "DDC-PREMIUM-DISABLE-2025"  # Alternative format
    ]
    
    return key.strip().upper() in [k.upper() for k in VALID_KEYS]


def get_valid_keys() -> list:
    """
    Get list of valid donation disable keys.
    
    Returns:
        list: List of valid keys that can be purchased
    """
    return [
        "DDC-DISABLE-2025-PREMIUM",
        "DDC-PREMIUM-DISABLE-2025"
    ]


def generate_sample_key() -> str:
    """
    Return the premium key that can be purchased.
    
    Returns:
        str: The premium key available for purchase
    """
    return "DDC-DISABLE-2025-PREMIUM"