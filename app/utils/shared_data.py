# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Shared data for the Flask application.
Used to share active containers and other data between different parts of the application.
"""

import os
import json
from threading import Lock

# Shared data with lock for thread safety
_shared_data_lock = Lock()
_active_containers = []

# Configuration paths
CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config"))
DOCKER_CONFIG_FILE = os.path.join(CONFIG_DIR, "docker_config.json")

def set_active_containers(container_list):
    """Sets the list of active containers."""
    global _active_containers
    with _shared_data_lock:
        _active_containers = container_list.copy() if container_list else []

def get_active_containers():
    """Returns the list of active containers."""
    with _shared_data_lock:
        return _active_containers.copy()

def load_active_containers_from_config():
    """Loads active containers from the Docker configuration."""
    try:
        if not os.path.exists(DOCKER_CONFIG_FILE):
            print(f"SHARED_DATA: Configuration file {DOCKER_CONFIG_FILE} not found.")
            return []
        
        with open(DOCKER_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Search for selected_servers list
        if 'selected_servers' in config and isinstance(config['selected_servers'], list):
            containers = config['selected_servers']
            print(f"SHARED_DATA: {len(containers)} active containers loaded from selected_servers.")
            set_active_containers(containers)
            return containers
        
        # Fallback: Use all servers as active
        if 'servers' in config and isinstance(config['servers'], list):
            containers = [server.get('docker_name') for server in config['servers'] 
                        if isinstance(server, dict) and 'docker_name' in server]
            print(f"SHARED_DATA: {len(containers)} active containers loaded from servers list (fallback).")
            set_active_containers(containers)
            return containers
        
        return []
    except Exception as e:
        print(f"SHARED_DATA: Error loading active containers: {e}")
        return []

# Load the active containers when importing the module
load_active_containers_from_config() 