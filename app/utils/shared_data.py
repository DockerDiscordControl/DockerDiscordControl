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
import glob
from threading import Lock

# Shared data with lock for thread safety
_shared_data_lock = Lock()
_active_containers = []

# Configuration paths
CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config"))
DOCKER_CONFIG_FILE = os.path.join(CONFIG_DIR, "docker_config.json")  # Legacy fallback
CONTAINERS_DIR = os.path.join(CONFIG_DIR, "containers")

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
    """Loads active containers from per-container configuration files."""
    try:
        # Check if containers directory exists
        if not os.path.exists(CONTAINERS_DIR):
            print(f"SHARED_DATA: Containers directory {CONTAINERS_DIR} not found.")
            return []

        # Find all JSON files in containers directory
        container_files = glob.glob(os.path.join(CONTAINERS_DIR, "*.json"))

        if not container_files:
            print(f"SHARED_DATA: No container configuration files found in {CONTAINERS_DIR}.")
            return []

        containers = []

        # Load each container configuration
        for config_file in container_files:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                # Check if container is active (default to True for backwards compatibility)
                is_active = config.get('active', True)

                # Extract container name from the configuration
                container_name = config.get('container_name')
                if container_name:
                    if is_active:
                        containers.append(container_name)
                        print(f"SHARED_DATA: Loaded ACTIVE container '{container_name}' from {os.path.basename(config_file)}")
                    else:
                        print(f"SHARED_DATA: Skipped INACTIVE container '{container_name}' from {os.path.basename(config_file)}")
                else:
                    print(f"SHARED_DATA: Warning - No container_name found in {os.path.basename(config_file)}")

            except Exception as e:
                print(f"SHARED_DATA: Error loading container config {os.path.basename(config_file)}: {e}")
                continue

        total_files = len(container_files)
        print(f"SHARED_DATA: {len(containers)} ACTIVE containers loaded from {total_files} total container files.")
        set_active_containers(containers)
        return containers

    except Exception as e:
        print(f"SHARED_DATA: Error loading active containers: {e}")
        return []

# Load the active containers when importing the module
load_active_containers_from_config() 