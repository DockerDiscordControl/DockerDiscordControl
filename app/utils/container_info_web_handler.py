# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Web UI handler for container info - saves to separate JSON files
"""

import logging
from typing import Dict, Any
from services.infrastructure.container_info_service import get_container_info_service, ContainerInfo
from utils.logging_utils import get_module_logger

logger = get_module_logger('container_info_web_handler')

def save_container_info_from_web(form_data: Dict[str, Any], container_names: list) -> Dict[str, bool]:
    """
    Save container info from Web UI form data to separate JSON files.
    
    Args:
        form_data: Form data from Web UI
        container_names: List of container names to process
        
    Returns:
        Dict with container names as keys and success status as values
    """
    info_service = get_container_info_service()
    results = {}
    
    for container_name in container_names:
        try:
            # Extract and create ContainerInfo object
            container_info = ContainerInfo(
                enabled=form_data.get(f'info_enabled_{container_name}', '0') == '1',
                show_ip=form_data.get(f'info_show_ip_{container_name}', '0') == '1',
                custom_ip=form_data.get(f'info_custom_ip_{container_name}', '').strip(),
                custom_port=form_data.get(f'info_custom_port_{container_name}', '').strip(),
                custom_text=form_data.get(f'info_custom_text_{container_name}', '').strip()
            )
            
            # Save via service
            result = info_service.save_container_info(container_name, container_info)
            results[container_name] = result.success
            
            if result.success:
                logger.info(f"Saved container info for {container_name} from Web UI")
            else:
                logger.error(f"Failed to save container info for {container_name} from Web UI: {result.error}")
                
        except Exception as e:
            logger.error(f"Error processing container info for {container_name}: {e}")
            results[container_name] = False
    
    return results

def load_container_info_for_web(container_names: list) -> Dict[str, Dict[str, Any]]:
    """
    Load container info from JSON files for Web UI display.
    
    Args:
        container_names: List of container names to load
        
    Returns:
        Dict with container names as keys and info dicts as values
    """
    info_service = get_container_info_service()
    results = {}
    
    for container_name in container_names:
        try:
            result = info_service.get_container_info(container_name)
            if result.success:
                info_data = result.data.to_dict()
            else:
                info_data = {
                    'enabled': False,
                    'show_ip': False,
                    'custom_ip': '',
                    'custom_port': '',
                    'custom_text': ''
                }
            results[container_name] = info_data
            logger.debug(f"Loaded container info for {container_name}: {info_data}")
        except Exception as e:
            logger.error(f"Error loading container info for {container_name}: {e}")
            results[container_name] = {
                'enabled': False,
                'show_ip': False,
                'custom_ip': '',
                'custom_port': '',
                'custom_text': ''
            }

    return results

def save_container_configs_from_web(servers_data: list) -> Dict[str, bool]:
    """
    Save container configuration data (allowed_actions, display_name, etc.) to individual container JSON files.

    Args:
        servers_data: List of server dictionaries from processed config

    Returns:
        Dict with container names as keys and success status as values
    """
    import json
    from pathlib import Path

    logger.info(f"[SAVE_DEBUG] save_container_configs_from_web called with {len(servers_data)} servers")

    results = {}
    containers_dir = Path('config/containers')

    if not containers_dir.exists():
        logger.error(f"Containers directory not found: {containers_dir}")
        return results

    for server in servers_data:
        container_name = server.get('docker_name') or server.get('container_name')
        if not container_name:
            logger.warning(f"Server data missing container name: {server}")
            continue

        try:
            container_file = containers_dir / f"{container_name}.json"

            # Load existing container config or create new one
            if container_file.exists():
                with open(container_file, 'r') as f:
                    container_config = json.load(f)
            else:
                container_config = {}

            # Update container config with server data
            container_config['container_name'] = container_name
            container_config['docker_name'] = container_name  # Required by status handlers
            container_config['name'] = container_name  # Alternative field for compatibility
            container_config['display_name'] = server.get('display_name', [container_name, container_name])
            container_config['allowed_actions'] = server.get('allowed_actions', ['status'])

            # Preserve existing info data if present
            if 'info' not in container_config:
                container_config['info'] = {
                    'enabled': False,
                    'show_ip': False,
                    'custom_ip': '',
                    'custom_port': '',
                    'custom_text': '',
                    'protected_enabled': False,
                    'protected_content': '',
                    'protected_password': ''
                }

            # Set order if provided
            if 'order' in server:
                container_config['order'] = server['order']

            # Set allow_detailed_status if provided
            if 'allow_detailed_status' in server:
                container_config['allow_detailed_status'] = server['allow_detailed_status']

            # Save updated config
            with open(container_file, 'w') as f:
                json.dump(container_config, f, indent=2)

            results[container_name] = True
            logger.info(f"[SAVE_DEBUG] Saved container config for {container_name}: actions={container_config.get('allowed_actions')}, display={container_config.get('display_name')}")

        except Exception as e:
            logger.error(f"Error saving container config for {container_name}: {e}")
            results[container_name] = False

    return results