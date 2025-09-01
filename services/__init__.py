# -*- coding: utf-8 -*-
"""
Services Package - Clean service architecture for DDC

This package contains professional business logic services organized by domain:
- infrastructure: Core infrastructure services (logging, container info, spam protection)  
- config: Configuration domain services (bot, docker, web, channels)
- mech: Donation and mech animation services

All services follow clean architecture patterns:
- Immutable dataclasses for type safety
- ServiceResult wrappers for consistent error handling
- Singleton pattern for resource management
- Atomic operations for data integrity
"""

import sys
import os

# Add the parent directory to Python path to ensure proper imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Infrastructure Services
from .infrastructure.container_info_service import get_container_info_service
from .infrastructure.action_log_service import get_action_log_service
from .infrastructure.spam_protection_service import get_spam_protection_service

# Config Services
from .config.unified_config_service import get_unified_config_service
from .config.bot_config_service import get_bot_config_service
from .config.docker_config_service import get_docker_config_service

# Mech Services
from .mech_service import get_mech_service

__all__ = [
    # Infrastructure
    'get_container_info_service',
    'get_action_log_service', 
    'get_spam_protection_service',
    # Config
    'get_unified_config_service',
    'get_bot_config_service',
    'get_docker_config_service',
    # Mech
    'get_mech_service'
]