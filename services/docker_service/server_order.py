# -*- coding: utf-8 -*-
"""
Utility for saving and loading server display order for DockerDiscordControl
"""
import os
import json
import logging
from typing import List, Dict, Any

# Setup logger
from utils.logging_utils import setup_logger
logger = setup_logger('ddc.server_order', level=logging.DEBUG)

# Base directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDER_FILE = os.path.join(BASE_DIR, "config", "server_order.json")

def save_server_order(server_order: List[str]) -> bool:
    """
    Save the server order to a persistent file
    
    Args:
        server_order: List of docker container names in the desired display order
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(ORDER_FILE), exist_ok=True)
        
        # Save to file
        with open(ORDER_FILE, 'w') as f:
            json.dump({"server_order": server_order}, f, indent=2)
            
        logger.info(f"Server order saved: {server_order}")
        return True
    except Exception as e:
        logger.error(f"Error saving server order: {e}")
        return False

def load_server_order() -> List[str]:
    """
    Load the server order from the persistent file
    
    Returns:
        List[str]: List of docker container names in the saved display order
    """
    try:
        if not os.path.exists(ORDER_FILE):
            logger.info("Server order file does not exist, returning empty list")
            return []
            
        with open(ORDER_FILE, 'r') as f:
            data = json.load(f)
            server_order = data.get("server_order", [])
            
        logger.info(f"Loaded server order: {server_order}")
        return server_order
    except Exception as e:
        logger.error(f"Error loading server order: {e}")
        return []

def update_server_order_from_config(config: Dict[str, Any]) -> bool:
    """
    Update the server order file from the main configuration
    
    Args:
        config: The main configuration dictionary
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Extract server order
        if "server_order" in config:
            # Server order is directly in the config
            server_order = config["server_order"]
        else:
            # Create order from servers list
            servers = config.get("servers", [])
            server_order = [s.get("docker_name") for s in servers if s.get("docker_name")]
            
        # Save the order
        return save_server_order(server_order)
    except Exception as e:
        logger.error(f"Error updating server order from config: {e}")
        return False 