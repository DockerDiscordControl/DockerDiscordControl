# =============================================================================
# SERVICE FIRST: Server Configuration Service
# =============================================================================

import logging
from typing import List, Dict, Any, Optional
from .config_service import load_config

logger = logging.getLogger('ddc.server_config_service')

class ServerConfigService:
    """Service First implementation for server configuration access.

    This service provides clean access to server configurations,
    hiding implementation details and providing validation.
    """

    def __init__(self):
        """Initialize the ServerConfigService."""
        logger.info("ServerConfigService initialized")

    def get_all_servers(self) -> List[Dict[str, Any]]:
        """Get all server configurations.

        Returns:
            List of server configurations, empty list if none
        """
        config = load_config()
        if not config:
            logger.warning("Config unavailable, returning empty server list")
            return []

        servers = config.get('servers', [])
        if not isinstance(servers, list):
            logger.error(f"Invalid servers configuration: expected list, got {type(servers)}")
            return []

        return servers

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