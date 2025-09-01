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
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContainerInfo':
        """Create ContainerInfo from dictionary data."""
        return cls(
            enabled=bool(data.get('enabled', False)),
            show_ip=bool(data.get('show_ip', False)),
            custom_ip=str(data.get('custom_ip', '')),
            custom_port=str(data.get('custom_port', '')),
            custom_text=str(data.get('custom_text', ''))
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert ContainerInfo to dictionary for storage."""
        return {
            'enabled': self.enabled,
            'show_ip': self.show_ip,
            'custom_ip': self.custom_ip,
            'custom_port': self.custom_port,
            'custom_text': self.custom_text
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class ContainerInfoService:
    """Clean service for managing container information with proper separation of concerns."""
    
    def __init__(self, config_dir: Optional[str] = None):
        """Initialize the container info service.
        
        Args:
            config_dir: Directory to store container info files. Defaults to config/container_info/
        """
        if config_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_dir = os.path.join(base_dir, "config", "container_info")
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Container info service initialized: {self.config_dir}")
    
    def get_container_info(self, container_name: str) -> ServiceResult:
        """Get container information by name.
        
        Args:
            container_name: Name of the container
            
        Returns:
            ServiceResult with ContainerInfo data or error
        """
        try:
            file_path = self.config_dir / f"{container_name}_info.json"
            
            if not file_path.exists():
                # Return default info for non-existent containers
                default_info = ContainerInfo(
                    enabled=False,
                    show_ip=False,
                    custom_ip='',
                    custom_port='',
                    custom_text=''
                )
                return ServiceResult(success=True, data=default_info)
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            container_info = ContainerInfo.from_dict(data)
            logger.debug(f"Loaded info for container: {container_name}")
            
            return ServiceResult(success=True, data=container_info)
            
        except Exception as e:
            error_msg = f"Error loading info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def save_container_info(self, container_name: str, container_info: ContainerInfo) -> ServiceResult:
        """Save container information.
        
        Args:
            container_name: Name of the container
            container_info: Container information to save
            
        Returns:
            ServiceResult indicating success or failure
        """
        try:
            file_path = self.config_dir / f"{container_name}_info.json"
            
            # Atomic write using temporary file
            temp_path = file_path.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(container_info.to_dict(), f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_path.rename(file_path)
            
            logger.info(f"Saved container info: {container_name}")
            return ServiceResult(success=True, data=container_info)
            
        except Exception as e:
            error_msg = f"Error saving info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def delete_container_info(self, container_name: str) -> ServiceResult:
        """Delete container information file.
        
        Args:
            container_name: Name of the container
            
        Returns:
            ServiceResult indicating success or failure
        """
        try:
            file_path = self.config_dir / f"{container_name}_info.json"
            
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Deleted container info: {container_name}")
            else:
                logger.debug(f"Container info file not found: {container_name}")
            
            return ServiceResult(success=True)
            
        except Exception as e:
            error_msg = f"Error deleting info for {container_name}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def list_all_containers(self) -> ServiceResult:
        """List all containers that have info files.
        
        Returns:
            ServiceResult with list of container names
        """
        try:
            container_names = []
            
            for file_path in self.config_dir.glob("*_info.json"):
                # Extract container name from filename
                container_name = file_path.stem.replace('_info', '')
                container_names.append(container_name)
            
            logger.debug(f"Found {len(container_names)} container info files")
            return ServiceResult(success=True, data=container_names)
            
        except Exception as e:
            error_msg = f"Error listing container info files: {e}"
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