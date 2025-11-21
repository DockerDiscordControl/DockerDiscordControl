# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Container Info Service - Manages container metadata with clean service architecture
"""

import docker
import os
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass
from utils.logging_utils import get_module_logger
from services.config.server_config_service import get_server_config_service

logger = get_module_logger('container_info_service')

@dataclass(frozen=True)
class ContainerInfo:
    """Immutable container information data structure."""
    enabled: bool
    show_ip: bool
    custom_ip: str
    custom_port: str
    custom_text: str
    # Protected information fields
    protected_enabled: bool
    protected_content: str
    protected_password: str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContainerInfo':
        """Create ContainerInfo from dictionary data."""
        return cls(
            enabled=bool(data.get('enabled', False)),
            show_ip=bool(data.get('show_ip', False)),
            custom_ip=str(data.get('custom_ip', '')),
            custom_port=str(data.get('custom_port', '')),
            custom_text=str(data.get('custom_text', '')),
            protected_enabled=bool(data.get('protected_enabled', False)),
            protected_content=str(data.get('protected_content', ''))[:250],  # Max 250 chars
            protected_password=str(data.get('protected_password', ''))[:60]   # Max 60 chars
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert ContainerInfo to dictionary for storage."""
        return {
            'enabled': self.enabled,
            'show_ip': self.show_ip,
            'custom_ip': self.custom_ip,
            'custom_port': self.custom_port,
            'custom_text': self.custom_text,
            'protected_enabled': self.protected_enabled,
            'protected_content': self.protected_content,
            'protected_password': self.protected_password
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class ContainerInfoService:
    """Clean service for managing container information using individual container JSON files."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize the container info service.

        Args:
            config_file: Path to docker config file (kept for compatibility, not used)
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.containers_dir = Path(base_dir) / "config" / "containers"
        self.config_file = Path(base_dir) / "config" / "docker_config.json"  # Keep for backward compatibility
        logger.info(f"Container info service initialized using container files in: {self.containers_dir}")
    
    def get_container_info(self, container_name: str) -> ServiceResult:
        """Get container information by name from individual container JSON file.

        Args:
            container_name: Name of the container

        Returns:
            ServiceResult with ContainerInfo data or error
        """
        try:
            # Try to find container JSON file
            container_file = self.containers_dir / f"{container_name}.json"

            if not container_file.exists():
                # Try alternative naming patterns
                for file in self.containers_dir.glob("*.json"):
                    with open(file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if (data.get('container_name') == container_name or
                            data.get('docker_name') == container_name or
                            data.get('name') == container_name):
                            container_file = file
                            break
                else:
                    # Container not found - return default info
                    default_info = ContainerInfo(
                        enabled=False,
                        show_ip=False,
                        custom_ip='',
                        custom_port='',
                        custom_text='',
                        protected_enabled=False,
                        protected_content='',
                        protected_password=''
                    )
                    logger.debug(f"Container file not found for: {container_name}")
                    return ServiceResult(success=True, data=default_info)

            # Read container configuration
            with open(container_file, 'r', encoding='utf-8') as f:
                container_data = json.load(f)

            # Extract info section
            info_data = container_data.get('info', {})
            container_info = ContainerInfo.from_dict(info_data)
            logger.debug(f"Loaded info for container {container_name} from {container_file.name}: enabled={container_info.enabled}")
            return ServiceResult(success=True, data=container_info)

        except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException) as e:
            error_msg = f"Error loading info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def save_container_info(self, container_name: str, container_info: ContainerInfo) -> ServiceResult:
        """Save container information to individual container JSON file.

        Args:
            container_name: Name of the container
            container_info: Container information to save

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            # Find container JSON file
            container_file = self.containers_dir / f"{container_name}.json"

            if not container_file.exists():
                # Try alternative naming patterns
                for file in self.containers_dir.glob("*.json"):
                    with open(file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if (data.get('container_name') == container_name or
                            data.get('docker_name') == container_name or
                            data.get('name') == container_name):
                            container_file = file
                            break
                else:
                    error_msg = f"Container file not found for: {container_name}"
                    logger.error(error_msg)
                    return ServiceResult(success=False, error=error_msg)

            # Read current container data
            with open(container_file, 'r', encoding='utf-8') as f:
                container_data = json.load(f)

            # Update info section
            container_data['info'] = container_info.to_dict()

            # Atomic write using temporary file
            temp_path = container_file.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(container_data, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_path.rename(container_file)

            logger.info(f"Saved container info to {container_file.name}: {container_name}")
            return ServiceResult(success=True, data=container_info)

        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            error_msg = f"Error saving info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def delete_container_info(self, container_name: str) -> ServiceResult:
        """Reset container information to defaults in individual container JSON file.

        Args:
            container_name: Name of the container

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            # Find container JSON file
            container_file = self.containers_dir / f"{container_name}.json"

            if not container_file.exists():
                # Try alternative naming patterns
                for file in self.containers_dir.glob("*.json"):
                    with open(file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if (data.get('container_name') == container_name or
                            data.get('docker_name') == container_name or
                            data.get('name') == container_name):
                            container_file = file
                            break
                else:
                    logger.debug(f"Container file not found for: {container_name}")
                    return ServiceResult(success=True)  # Not an error if container doesn't exist

            # Read current container data
            with open(container_file, 'r', encoding='utf-8') as f:
                container_data = json.load(f)

            # Reset info section to defaults
            container_data['info'] = {
                'enabled': False,
                'show_ip': False,
                'custom_ip': '',
                'custom_port': '',
                'custom_text': '',
                'protected_enabled': False,
                'protected_content': '',
                'protected_password': ''
            }

            # Atomic write using temporary file
            temp_path = container_file.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(container_data, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_path.rename(container_file)

            logger.info(f"Reset container info to defaults: {container_name}")
            return ServiceResult(success=True)

        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            error_msg = f"Error resetting info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def list_all_containers(self) -> ServiceResult:
        """List all containers from docker_config.json servers array.

        Returns:
            ServiceResult with list of container names
        """
        try:
            container_names = []

            if not self.config_file.exists():
                logger.debug("Docker config file not found, returning empty list")
                return ServiceResult(success=True, data=container_names)

            with open(self.config_file, 'r', encoding='utf-8') as f:
                docker_config = json.load(f)

            # Extract container names from servers array
            # SERVICE FIRST: Use ServerConfigService instead of direct config access
            server_config_service = get_server_config_service()
            servers = server_config_service.get_all_servers()
            for server in servers:
                # Use docker_name as primary, fallback to name
                container_name = server.get('docker_name') or server.get('name')
                if container_name:
                    container_names.append(container_name)

            logger.debug(f"Found {len(container_names)} containers in docker config")
            return ServiceResult(success=True, data=container_names)

        except (RuntimeError, docker.errors.APIError, docker.errors.DockerException) as e:
            error_msg = f"Error listing containers from docker config: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)

# Singleton instance
_container_info_service = None

def get_container_info_service() -> ContainerInfoService:
    """Get the global container info service instance.
    
    Returns:
        ContainerInfoService instance
    """
    global _container_info_service
    if _container_info_service is None:
        _container_info_service = ContainerInfoService()
    return _container_info_service