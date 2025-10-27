# -*- coding: utf-8 -*-
"""
Container Info Service - Manages container metadata with clean service architecture
"""

import os
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
from dataclasses import dataclass
from utils.logging_utils import get_module_logger

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
    """Clean service for managing container information using docker_config.json as single source."""

    def __init__(self, config_file: Optional[str] = None):
        """Initialize the container info service.

        Args:
            config_file: Path to docker config file. Defaults to config/docker_config.json
        """
        if config_file is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_file = os.path.join(base_dir, "config", "docker_config.json")

        self.config_file = Path(config_file)
        logger.info(f"Container info service initialized using: {self.config_file}")
    
    def get_container_info(self, container_name: str) -> ServiceResult:
        """Get container information by name from docker_config.json.

        Args:
            container_name: Name of the container

        Returns:
            ServiceResult with ContainerInfo data or error
        """
        try:
            if not self.config_file.exists():
                # Return default info if docker config doesn't exist
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
                return ServiceResult(success=True, data=default_info)

            with open(self.config_file, 'r', encoding='utf-8') as f:
                docker_config = json.load(f)

            # Find container in servers array
            servers = docker_config.get('servers', [])
            for server in servers:
                if (server.get('name') == container_name or
                    server.get('docker_name') == container_name):

                    # Extract info section
                    info_data = server.get('info', {})
                    container_info = ContainerInfo.from_dict(info_data)
                    logger.debug(f"Loaded info for container: {container_name}")
                    return ServiceResult(success=True, data=container_info)

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
            logger.debug(f"Container not found, returning default info: {container_name}")
            return ServiceResult(success=True, data=default_info)

        except Exception as e:
            error_msg = f"Error loading info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def save_container_info(self, container_name: str, container_info: ContainerInfo) -> ServiceResult:
        """Save container information to docker_config.json.

        Args:
            container_name: Name of the container
            container_info: Container information to save

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            if not self.config_file.exists():
                error_msg = f"Docker config file not found: {self.config_file}"
                logger.error(error_msg)
                return ServiceResult(success=False, error=error_msg)

            with open(self.config_file, 'r', encoding='utf-8') as f:
                docker_config = json.load(f)

            # Find and update container in servers array
            servers = docker_config.get('servers', [])
            container_found = False

            for server in servers:
                if (server.get('name') == container_name or
                    server.get('docker_name') == container_name):

                    # Update info section
                    server['info'] = container_info.to_dict()
                    container_found = True
                    break

            if not container_found:
                error_msg = f"Container not found in docker config: {container_name}"
                logger.error(error_msg)
                return ServiceResult(success=False, error=error_msg)

            # Atomic write using temporary file
            temp_path = self.config_file.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(docker_config, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_path.rename(self.config_file)

            logger.info(f"Saved container info to docker config: {container_name}")
            return ServiceResult(success=True, data=container_info)

        except Exception as e:
            error_msg = f"Error saving info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def delete_container_info(self, container_name: str) -> ServiceResult:
        """Reset container information to defaults in docker_config.json.

        Args:
            container_name: Name of the container

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            if not self.config_file.exists():
                error_msg = f"Docker config file not found: {self.config_file}"
                logger.error(error_msg)
                return ServiceResult(success=False, error=error_msg)

            with open(self.config_file, 'r', encoding='utf-8') as f:
                docker_config = json.load(f)

            # Find and reset container info in servers array
            servers = docker_config.get('servers', [])
            container_found = False

            for server in servers:
                if (server.get('name') == container_name or
                    server.get('docker_name') == container_name):

                    # Reset info section to defaults
                    server['info'] = {
                        'enabled': False,
                        'show_ip': False,
                        'custom_ip': '',
                        'custom_port': '',
                        'custom_text': '',
                        'protected_enabled': False,
                        'protected_content': '',
                        'protected_password': ''
                    }
                    container_found = True
                    break

            if not container_found:
                logger.debug(f"Container not found in docker config: {container_name}")
                return ServiceResult(success=True)  # Not an error if container doesn't exist

            # Atomic write using temporary file
            temp_path = self.config_file.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(docker_config, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_path.rename(self.config_file)

            logger.info(f"Reset container info to defaults: {container_name}")
            return ServiceResult(success=True)

        except Exception as e:
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
            servers = docker_config.get('servers', [])
            for server in servers:
                # Use docker_name as primary, fallback to name
                container_name = server.get('docker_name') or server.get('name')
                if container_name:
                    container_names.append(container_name)

            logger.debug(f"Found {len(container_names)} containers in docker config")
            return ServiceResult(success=True, data=container_names)

        except Exception as e:
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