"""
Donation configuration storage - separate from main config due to permission issues.
Stores donation disable keys in a separate JSON file with write permissions.
"""

import json
import os
from typing import Optional

# Dynamic config file path - same pattern as other config files
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, "..", "config"))
DONATION_CONFIG_FILE = os.path.join(CONFIG_DIR, "donation_keys.json")

# Ensure config directory exists
os.makedirs(CONFIG_DIR, exist_ok=True)

def load_donation_config() -> dict:
    """
    Load donation configuration from file.
    
    Returns:
        dict: Donation configuration data
    """
    try:
        if os.path.exists(DONATION_CONFIG_FILE):
            with open(DONATION_CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception:
        return {}

def save_donation_config(config: dict) -> bool:
    """
    Save donation configuration to file.
    
    Args:
        config: Configuration dictionary to save
        
    Returns:
        bool: True if save successful, False otherwise
    """
    try:
        with open(DONATION_CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False

def get_donation_disable_key() -> Optional[str]:
    """
    Get the current donation disable key.
    
    Returns:
        str: The donation disable key, or None if not set
    """
    config = load_donation_config()
    key = config.get('donation_disable_key', '').strip()
    return key if key else None

def set_donation_disable_key(key: str) -> bool:
    """
    Set the donation disable key.
    
    Args:
        key: The donation disable key to set (empty string to remove)
        
    Returns:
        bool: True if save successful, False otherwise
    """
    config = load_donation_config()
    
    if key and key.strip():
        config['donation_disable_key'] = key.strip()
    else:
        # Remove key if empty
        if 'donation_disable_key' in config:
            del config['donation_disable_key']
    
    config['last_updated'] = '2025-08-26'
    return save_donation_config(config)

def is_donations_disabled() -> bool:
    """
    Check if donations are disabled by a valid key.
    
    Returns:
        bool: True if donations are disabled, False otherwise
    """
    key = get_donation_disable_key()
    if not key:
        return False
    
    # Validate key using crypto module directly to avoid circular import
    from utils.key_crypto import get_valid_donation_keys
    try:
        valid_keys = get_valid_donation_keys()
        return key.strip().upper() in [k.upper() for k in valid_keys]
    except Exception:
        return False