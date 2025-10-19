# -*- coding: utf-8 -*-
"""
Services Package - Clean service architecture for DDC

This package contains professional business logic services organized by domain:
- infrastructure: Core infrastructure services (logging, container info, spam protection)  
- config: Unified configuration service (replaces old config_loader/manager)
- docker_service: Docker container management utilities
- donation: Donation system and disable key management
- mech: Donation mech animation and state services
- scheduling: Task scheduler and helper services

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
from .config.config_service import get_config_service

# Mech Services
from .mech.mech_service import get_mech_service
# Removed deprecated mech_animation_service - use png_to_webp_service directly

__all__ = [
    # Infrastructure
    'get_container_info_service',
    'get_action_log_service', 
    'get_spam_protection_service',
    # Config
    'get_config_service',
    # Mech
    'get_mech_service'
]