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
    Validate a donation disable key with complex format for authenticity.
    
    Args:
        key: The key to validate (complex license-style format)
        
    Returns:
        bool: True if key is valid, False otherwise
    """
    if not key:
        return False
    
    # Complex license-style keys that look authentic for purchase
    VALID_KEYS = [
        "DDC-PRO-24K5-9XH7-M3NQ-YZEF-2025",        # Professional license style
        "DDC-LIFETIME-8F9A-3P2K-7QLM-BHXC-2025",   # Lifetime license style  
        "DOCKER-DISCORD-CTRL-9G4B-5ZNW-PREMIUM",   # Full product name style
        "DDC-COMMERCIAL-KL8E-4RTS-6MQV-DISABLE",   # Commercial license
        "DDC-2025-ENTERPRISE-3YH9-BMKX-7FQL-PRO"   # Enterprise edition
    ]
    
    return key.strip().upper() in [k.upper() for k in VALID_KEYS]


def get_valid_keys() -> list:
    """
    Get list of valid donation disable keys.
    
    Returns:
        list: List of valid keys that can be purchased
    """
    return [
        "DDC-PRO-24K5-9XH7-M3NQ-YZEF-2025",
        "DDC-LIFETIME-8F9A-3P2K-7QLM-BHXC-2025",   
        "DOCKER-DISCORD-CTRL-9G4B-5ZNW-PREMIUM",
        "DDC-COMMERCIAL-KL8E-4RTS-6MQV-DISABLE",
        "DDC-2025-ENTERPRISE-3YH9-BMKX-7FQL-PRO"
    ]


def generate_sample_key() -> str:
    """
    Return the main premium key that can be purchased.
    
    Returns:
        str: The premium key available for purchase
    """
    return "DDC-PRO-24K5-9XH7-M3NQ-YZEF-2025"