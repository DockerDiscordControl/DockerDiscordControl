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
    from utils.donation_config import is_donations_disabled as check_donation_config
    
    try:
        return check_donation_config()
    except Exception:
        # If any error occurs, default to donations enabled
        return False


def validate_donation_key(key: str) -> bool:
    """
    Validate a donation disable key with complex format for authenticity.
    
    Args:
        key: The key to validate (complex license-style format)
        
    Returns:
        bool: True if key is valid, False otherwise
    """
    if not key:
        return False
    
    # Get valid keys from encrypted storage
    from utils.key_crypto import get_valid_donation_keys
    try:
        valid_keys = get_valid_donation_keys()
        return key.strip().upper() in [k.upper() for k in valid_keys]
    except Exception:
        # Fallback: If crypto module fails, deny access (fail secure)
        return False


def get_valid_keys() -> list:
    """
    Get list of valid donation disable keys.
    
    Returns:
        list: List of valid keys that can be purchased
    """
    from utils.key_crypto import get_valid_donation_keys
    try:
        return get_valid_donation_keys()
    except Exception:
        # Fallback: If crypto module fails, return empty list
        return []


def generate_sample_key() -> str:
    """
    Return the main premium key that can be purchased.
    
    Returns:
        str: The premium key available for purchase
    """
    return "DDC-PRO-24K5-9XH7-M3NQ-YZEF-2025"