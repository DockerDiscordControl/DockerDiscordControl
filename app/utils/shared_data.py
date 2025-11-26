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

import docker
import os
import json
import glob
from threading import Lock
from utils.logging_utils import get_module_logger

# Setup logger
logger = get_module_logger('shared_data')

# Shared data with lock for thread safety
_shared_data_lock = Lock()
_active_containers = []

# Configuration paths
from pathlib import Path
try:
    CONFIG_DIR = Path(__file__).parents[2] / "config"
except Exception:
    CONFIG_DIR = Path("config")

DOCKER_CONFIG_FILE = CONFIG_DIR / "docker_config.json"  # Legacy fallback
CONTAINERS_DIR = CONFIG_DIR / "containers"

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
        if not CONTAINERS_DIR.exists():
            logger.warning(f"Containers directory {CONTAINERS_DIR} not found.")
            return []

        # Find all JSON files in containers directory
        container_files = list(CONTAINERS_DIR.glob("*.json"))

        if not container_files:
            logger.warning(f"No container configuration files found in {CONTAINERS_DIR}.")
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
                        logger.info(f"Loaded ACTIVE container '{container_name}' from {config_file.name}")
                    else:
                        logger.info(f"Skipped INACTIVE container '{container_name}' from {config_file.name}")
                else:
                    logger.warning(f"No container_name found in {config_file.name}")

            except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
                logger.error(f"Error loading container config {config_file.name}: {e}")
                continue

        total_files = len(container_files)
        logger.info(f"{len(containers)} ACTIVE containers loaded from {total_files} total container files.")
        set_active_containers(containers)
        return containers

    except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
        logger.error(f"Error loading active containers: {e}")
        return []

# Load the active containers when importing the module
load_active_containers_from_config()
