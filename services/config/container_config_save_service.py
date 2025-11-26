# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
SERVICE FIRST: Container Configuration Save Service - SINGLE POINT OF TRUTH
"""

import logging
import json
import tempfile
from pathlib import Path
from typing import Dict, Any
import os

logger = logging.getLogger('ddc.container_config_save_service')

class ContainerConfigSaveService:
    """Service First implementation for saving container configurations.

    SINGLE POINT OF TRUTH: Saves ONLY to individual container JSON files
    in /config/containers/*.json
    """

    def __init__(self):
        """Initialize the ContainerConfigSaveService."""
        # Robust absolute path relative to project root (3 levels up from services/config/container_config_save_service.py)
        self.base_dir = Path(__file__).parents[2]
        self.containers_dir = self.base_dir / 'config' / 'containers'

        # Ensure containers directory exists
        self.containers_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"ContainerConfigSaveService initialized - saving to {self.containers_dir}")

    def save_container_config(self, container_name: str, config: Dict[str, Any]) -> bool:
        """Save a container configuration to its JSON file.

        Args:
            container_name: Name of the container
            config: Configuration dictionary to save

        Returns:
            True if successful, False otherwise
        """
        try:
            # Determine file path
            config_file = self.containers_dir / f"{container_name}.json"

            # Write atomically using temp file
            temp_dir = str(self.containers_dir)
            fd, temp_path = tempfile.mkstemp(dir=temp_dir, text=True, suffix='.json.tmp')

            try:
                # Write to temp file
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk

                # Atomic rename (POSIX) or move (Windows)
                if os.name == 'posix':
                    os.rename(temp_path, config_file)
                else:
                    # Windows: remove target first if exists
                    if config_file.exists():
                        config_file.unlink()
                    os.rename(temp_path, config_file)
            except Exception:
                # Cleanup temp file on error
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass  # Best effort cleanup
                raise

            logger.info(f"Saved container config for {container_name} to {config_file}")
            return True

        except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError) as e:
            logger.error(f"Error saving container config for {container_name}: {e}", exc_info=True)
            return False

    def delete_container_config(self, container_name: str) -> bool:
        """Delete a container configuration file.

        Args:
            container_name: Name of the container

        Returns:
            True if successful or file doesn't exist, False on error
        """
        try:
            config_file = self.containers_dir / f"{container_name}.json"

            if config_file.exists():
                config_file.unlink()
                logger.info(f"Deleted container config for {container_name}")
            else:
                logger.debug(f"Container config for {container_name} doesn't exist")

            return True

        except (RuntimeError, OSError, PermissionError) as e:
            logger.error(f"Error deleting container config for {container_name}: {e}", exc_info=True)
            return False

# Singleton instance management
_container_config_save_service_instance = None

def get_container_config_save_service() -> ContainerConfigSaveService:
    """Get singleton instance of ContainerConfigSaveService.

    Returns:
        ContainerConfigSaveService instance
    """
    global _container_config_save_service_instance

    if _container_config_save_service_instance is None:
        _container_config_save_service_instance = ContainerConfigSaveService()
        logger.info("Created new ContainerConfigSaveService singleton instance")

    return _container_config_save_service_instance

def reset_container_config_save_service():
    """Reset the singleton instance (mainly for testing)."""
    global _container_config_save_service_instance
    _container_config_save_service_instance = None
    logger.info("ContainerConfigSaveService singleton reset")
