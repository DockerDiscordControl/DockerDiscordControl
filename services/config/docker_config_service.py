# -*- coding: utf-8 -*-
"""
Docker Config Service - Manages Docker container/server configuration
"""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

@dataclass(frozen=True)
class ServerInfo:
    """Immutable server info data structure."""
    enabled: bool
    show_ip: bool
    custom_ip: str
    custom_port: str
    custom_text: str
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ServerInfo':
        """Create ServerInfo from dictionary data."""
        return cls(
            enabled=bool(data.get('enabled', False)),
            show_ip=bool(data.get('show_ip', False)),
            custom_ip=str(data.get('custom_ip', '')),
            custom_port=str(data.get('custom_port', '')),
            custom_text=str(data.get('custom_text', ''))
        )
    
    def to_dict(self) -> dict:
        """Convert ServerInfo to dictionary for storage."""
        return {
            'enabled': self.enabled,
            'show_ip': self.show_ip,
            'custom_ip': self.custom_ip,
            'custom_port': self.custom_port,
            'custom_text': self.custom_text
        }

@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration data structure."""
    name: str
    docker_name: str
    allowed_actions: List[str]
    info: ServerInfo
    order: int
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ServerConfig':
        """Create ServerConfig from dictionary data."""
        return cls(
            name=str(data.get('name', '')),
            docker_name=str(data.get('docker_name', '')),
            allowed_actions=list(data.get('allowed_actions', [])),
            info=ServerInfo.from_dict(data.get('info', {})),
            order=int(data.get('order', 0))
        )
    
    def to_dict(self) -> dict:
        """Convert ServerConfig to dictionary for storage."""
        return {
            'name': self.name,
            'docker_name': self.docker_name,
            'allowed_actions': self.allowed_actions,
            'info': self.info.to_dict(),
            'order': self.order
        }

@dataclass(frozen=True)
class DockerConfig:
    """Immutable docker configuration data structure."""
    servers: List[ServerConfig]
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DockerConfig':
        """Create DockerConfig from dictionary data."""
        servers_data = data.get('servers', [])
        servers = [ServerConfig.from_dict(server_data) for server_data in servers_data]
        return cls(servers=servers)
    
    def to_dict(self) -> dict:
        """Convert DockerConfig to dictionary for storage."""
        return {
            'servers': [server.to_dict() for server in self.servers]
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[any] = None
    error: Optional[str] = None

class DockerConfigService:
    """Clean service for managing Docker server configuration."""
    
    def __init__(self, config_dir: Optional[str] = None):
        """Initialize the docker config service."""
        if config_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            config_dir = base_dir / "config"
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "docker_config.json"
    
    def get_config(self) -> ServiceResult:
        """Get docker configuration."""
        try:
            if not self.config_file.exists():
                default_config = DockerConfig(servers=[])
                return ServiceResult(success=True, data=default_config)
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            config = DockerConfig.from_dict(data)
            return ServiceResult(success=True, data=config)
            
        except Exception as e:
            error_msg = f"Error loading docker config: {e}"
            return ServiceResult(success=False, error=error_msg)
    
    def save_config(self, config: DockerConfig) -> ServiceResult:
        """Save docker configuration."""
        try:
            # Atomic write
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
            temp_file.replace(self.config_file)
            
            return ServiceResult(success=True, data=config)
            
        except Exception as e:
            error_msg = f"Error saving docker config: {e}"
            return ServiceResult(success=False, error=error_msg)
    
    def get_server_config(self, server_name: str) -> ServiceResult:
        """Get configuration for a specific server."""
        try:
            config_result = self.get_config()
            if not config_result.success:
                return config_result
            
            for server in config_result.data.servers:
                if server.name == server_name:
                    return ServiceResult(success=True, data=server)
            
            return ServiceResult(success=False, error=f"Server {server_name} not found")
            
        except Exception as e:
            error_msg = f"Error getting server config for {server_name}: {e}"
            return ServiceResult(success=False, error=error_msg)
    
    def update_server_config(self, server_name: str, new_server_config: ServerConfig) -> ServiceResult:
        """Update configuration for a specific server."""
        try:
            config_result = self.get_config()
            if not config_result.success:
                return config_result
            
            # Find and update server
            updated_servers = []
            server_found = False
            
            for server in config_result.data.servers:
                if server.name == server_name:
                    updated_servers.append(new_server_config)
                    server_found = True
                else:
                    updated_servers.append(server)
            
            if not server_found:
                return ServiceResult(success=False, error=f"Server {server_name} not found")
            
            updated_config = DockerConfig(servers=updated_servers)
            return self.save_config(updated_config)
            
        except Exception as e:
            error_msg = f"Error updating server config for {server_name}: {e}"
            return ServiceResult(success=False, error=error_msg)

# Singleton instance
_docker_config_service = None

def get_docker_config_service() -> DockerConfigService:
    """Get the global docker config service instance."""
    global _docker_config_service
    if _docker_config_service is None:
        _docker_config_service = DockerConfigService()
    return _docker_config_service