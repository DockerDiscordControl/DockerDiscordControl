# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
SERVICE FIRST: Server Configuration Service - SINGLE POINT OF TRUTH
"""

import docker
import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from .config_service import load_config

logger = logging.getLogger('ddc.server_config_service')

class ServerConfigService:
    """Service First implementation for server configuration access.

    SINGLE POINT OF TRUTH: Reads ONLY from individual container JSON files
    in /config/containers/*.json - NOT from docker_config.json servers array!
    """

    def __init__(self):
        """Initialize the ServerConfigService."""
        self._cache: Optional[List[Dict[str, Any]]] = None
        logger.info("ServerConfigService initialized - Single Point of Truth from container JSONs")

    def _load_container_configs(self) -> List[Dict[str, Any]]:
        """Load all container configurations from individual JSON files.

        Returns:
            List of container configurations from /config/containers/*.json
        """
        containers = []

        try:
            # Get base directory
            config = load_config()
            if not config:
                logger.warning("Config unavailable, cannot load container configs")
                return []

            # Use environment variable or current directory in development
            import os
            base_dir = os.environ.get('DDC_BASE_DIR', config.get('base_dir', os.getcwd() if os.path.exists('config/containers') else '/app'))
            containers_dir = Path(base_dir) / 'config' / 'containers'

            if not containers_dir.exists():
                logger.warning(f"Containers directory not found: {containers_dir}")
                return []

            # Read each JSON file in containers directory
            for json_file in containers_dir.glob('*.json'):
                try:
                    with open(json_file, 'r') as f:
                        container_data = json.load(f)

                        # Map container_name to docker_name for compatibility
                        if 'container_name' in container_data:
                            container_data['docker_name'] = container_data['container_name']
                            # IMPORTANT: Don't overwrite 'name' if it already exists!
                            # The 'name' field should match docker_name for status lookups
                            if 'name' not in container_data:
                                container_data['name'] = container_data['container_name']

                        # Ensure we have essential fields
                        if 'docker_name' not in container_data:
                            logger.warning(f"Container config {json_file.name} missing docker_name/container_name")
                            continue

                        # Add allowed_actions if missing
                        if 'allowed_actions' not in container_data:
                            container_data['allowed_actions'] = ['status']

                        # Add order if missing
                        if 'order' not in container_data:
                            container_data['order'] = 999

                        # IMPORTANT: Only include active containers (default to active if field missing)
                        is_active = container_data.get('active', True)
                        if is_active:
                            containers.append(container_data)
                            logger.debug(f"Loaded ACTIVE container config: {json_file.name}")
                        else:
                            logger.debug(f"Skipped INACTIVE container config: {json_file.name}")

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in {json_file}: {e}")
                except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException, json.JSONDecodeError) as e:
                    logger.error(f"Error reading {json_file}: {e}", exc_info=True)

            # Count total containers including inactive
            total_containers = 0
            for json_file in containers_dir.glob('*.json'):
                total_containers += 1

            logger.info(f"Loaded {len(containers)} ACTIVE container configurations from {total_containers} total JSON files")

        except (IOError, OSError, PermissionError, RuntimeError, docker.errors.APIError, docker.errors.DockerException, json.JSONDecodeError) as e:
            logger.error(f"Error loading container configs: {e}", exc_info=True)

        return containers

    def get_all_servers(self) -> List[Dict[str, Any]]:
        """Get all server configurations from individual container JSONs.

        Returns:
            List of server configurations from /config/containers/*.json
        """
        # Always reload to ensure we have latest data (Single Point of Truth)
        self._cache = self._load_container_configs()
        return self._cache if self._cache else []

    def get_valid_containers(self) -> List[Dict[str, str]]:
        """Get list of valid containers with docker_name.

        Returns:
            List of dicts with 'display' and 'docker_name' keys
        """
        servers = self.get_all_servers()
        containers = []

        for server in servers:
            if not isinstance(server, dict):
                continue

            docker_name = server.get('docker_name')
            if docker_name and isinstance(docker_name, str):
                containers.append({
                    'display': docker_name,
                    'docker_name': docker_name
                })

        return containers

    def get_ordered_servers(self) -> List[Dict[str, Any]]:
        """Get servers sorted by their order field.

        Returns:
            List of server configurations sorted by order
        """
        servers = self.get_all_servers()
        return sorted(servers, key=lambda s: s.get('order', 999))

    def get_server_by_docker_name(self, docker_name: str) -> Optional[Dict[str, Any]]:
        """Get server configuration by docker name.

        Args:
            docker_name: Docker container name

        Returns:
            Server configuration dict or None if not found
        """
        servers = self.get_all_servers()

        for server in servers:
            if server.get('docker_name') == docker_name:
                return server

        return None

    def validate_server_config(self, server: Any) -> bool:
        """Validate that server config has expected format.

        Args:
            server: Server configuration to validate

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(server, dict):
            return False

        # Check required fields
        docker_name = server.get('docker_name')
        if not docker_name or not isinstance(docker_name, str):
            return False

        return True

    def get_base_directory(self) -> str:
        """Get base directory from configuration.

        Returns:
            Base directory path, defaults to '/app'
        """
        config = load_config()
        if not config:
            return '/app'

        return config.get('base_dir', '/app')

# Singleton instance
_server_config_service_instance = None

def get_server_config_service() -> ServerConfigService:
    """Get singleton instance of ServerConfigService.

    Returns:
        ServerConfigService instance
    """
    global _server_config_service_instance
    if _server_config_service_instance is None:
        _server_config_service_instance = ServerConfigService()
    return _server_config_service_instance
