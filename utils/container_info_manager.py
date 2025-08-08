# -*- coding: utf-8 -*-
"""
Container Info Manager - Handles separate info.json files for each container
"""

import os
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
from utils.logging_utils import get_module_logger

logger = get_module_logger('container_info_manager')

class ContainerInfoManager:
    """Manages container information stored in separate JSON files."""
    
    def __init__(self, config_dir: str = None):
        """Initialize the container info manager.
        
        Args:
            config_dir: Directory to store container info files. Defaults to config/container_info/
        """
        if config_dir is None:
            # Use the standard config directory + container_info subdirectory
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_dir = os.path.join(base_dir, "config", "container_info")
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Container info directory: {self.config_dir}")
    
    def _get_info_file_path(self, container_name: str) -> Path:
        """Get the path to the info file for a specific container.
        
        Args:
            container_name: Name of the container
            
        Returns:
            Path to the container's info.json file
        """
        # Sanitize container name for filename
        safe_name = "".join(c for c in container_name if c.isalnum() or c in '-_').lower()
        return self.config_dir / f"{safe_name}_info.json"
    
    def _validate_info_data(self, info_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and sanitize container info data for security."""
        validated = {}
        
        # Boolean fields - ensure they are actually boolean
        validated['enabled'] = bool(info_data.get('enabled', False))
        validated['show_ip'] = bool(info_data.get('show_ip', False))
        
        # String fields with length limits
        custom_text = str(info_data.get('custom_text', '')).strip()
        validated['custom_text'] = custom_text[:250]  # Enforce 250 char limit
        
        custom_ip = str(info_data.get('custom_ip', '')).strip()
        validated['custom_ip'] = custom_ip[:255]  # Max hostname length
        
        custom_port = str(info_data.get('custom_port', '')).strip()
        validated['custom_port'] = custom_port[:5]  # Max port length
        
        # Preserve metadata if present
        if 'created_at' in info_data:
            validated['created_at'] = info_data['created_at']
        if 'last_updated' in info_data:
            validated['last_updated'] = info_data['last_updated']
            
        return validated
    
    def load_container_info(self, container_name: str) -> Dict[str, Any]:
        """Load container information from its JSON file.
        
        Args:
            container_name: Name of the container
            
        Returns:
            Dictionary containing container info, or default values if file doesn't exist
        """
        info_file = self._get_info_file_path(container_name)
        
        # Default container info structure
        default_info = {
            "enabled": False,
            "show_ip": False,
            "custom_ip": "",
            "custom_port": "",
            "custom_text": "",
            "last_updated": None,
            "created_at": None
        }
        
        if not info_file.exists():
            logger.debug(f"Info file for {container_name} does not exist, returning defaults")
            return default_info
        
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                info_data = json.load(f)
            
            # Merge with defaults to ensure all keys exist
            for key, default_value in default_info.items():
                if key not in info_data:
                    info_data[key] = default_value
            
            logger.debug(f"Loaded info for {container_name}: {info_data}")
            return info_data
            
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading info file for {container_name}: {e}")
            return default_info
    
    def save_container_info(self, container_name: str, info_data: Dict[str, Any]) -> bool:
        """Save container information to its JSON file.
        
        Args:
            container_name: Name of the container
            info_data: Dictionary containing container info to save
            
        Returns:
            True if successful, False otherwise
        """
        info_file = self._get_info_file_path(container_name)
        
        try:
            # Validate and sanitize data
            validated_data = self._validate_info_data(info_data)
            
            # Add metadata
            from datetime import datetime, timezone
            validated_data['last_updated'] = datetime.now(timezone.utc).isoformat()
            
            # Create created_at if it doesn't exist
            if 'created_at' not in validated_data or validated_data['created_at'] is None:
                validated_data['created_at'] = validated_data['last_updated']
            
            # Ensure directory exists
            info_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to temporary file first, then rename (atomic operation)
            temp_file = info_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(validated_data, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_file.rename(info_file)
            
            logger.info(f"Saved info for {container_name} to {info_file}")
            return True
            
        except (IOError, OSError) as e:
            logger.error(f"Error saving info file for {container_name}: {e}")
            return False
    
    def delete_container_info(self, container_name: str) -> bool:
        """Delete the info file for a container.
        
        Args:
            container_name: Name of the container
            
        Returns:
            True if successful or file didn't exist, False on error
        """
        info_file = self._get_info_file_path(container_name)
        
        if not info_file.exists():
            return True
        
        try:
            info_file.unlink()
            logger.info(f"Deleted info file for {container_name}")
            return True
        except OSError as e:
            logger.error(f"Error deleting info file for {container_name}: {e}")
            return False
    
    def list_containers_with_info(self) -> List[str]:
        """Get a list of all containers that have info files.
        
        Returns:
            List of container names that have info files
        """
        containers = []
        
        if not self.config_dir.exists():
            return containers
        
        for info_file in self.config_dir.glob("*_info.json"):
            # Extract container name from filename
            filename = info_file.stem  # Remove .json extension
            if filename.endswith('_info'):
                container_name = filename[:-5]  # Remove _info suffix
                containers.append(container_name)
        
        return containers
    
    def update_container_info(self, container_name: str, **kwargs) -> bool:
        """Update specific fields in container info.
        
        Args:
            container_name: Name of the container
            **kwargs: Fields to update
            
        Returns:
            True if successful, False otherwise
        """
        # Load current info
        current_info = self.load_container_info(container_name)
        
        # Update with provided values
        current_info.update(kwargs)
        
        # Save updated info
        return self.save_container_info(container_name, current_info)

# Global instance
_container_info_manager = None

def get_container_info_manager() -> ContainerInfoManager:
    """Get the global container info manager instance.
    
    Returns:
        ContainerInfoManager instance
    """
    global _container_info_manager
    if _container_info_manager is None:
        _container_info_manager = ContainerInfoManager()
    return _container_info_manager