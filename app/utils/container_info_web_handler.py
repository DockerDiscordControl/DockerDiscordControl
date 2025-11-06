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
            # Extract and create ContainerInfo object with all required parameters
            container_info = ContainerInfo(
                enabled=form_data.get(f'info_enabled_{container_name}', '0') == '1',
                show_ip=form_data.get(f'info_show_ip_{container_name}', '0') == '1',
                custom_ip=form_data.get(f'info_custom_ip_{container_name}', '').strip(),
                custom_port=form_data.get(f'info_custom_port_{container_name}', '').strip(),
                custom_text=form_data.get(f'info_custom_text_{container_name}', '').strip(),
                # Add protected fields with defaults (not exposed in current UI)
                protected_enabled=form_data.get(f'info_protected_enabled_{container_name}', '0') == '1',
                protected_content=form_data.get(f'info_protected_content_{container_name}', '').strip(),
                protected_password=form_data.get(f'info_protected_password_{container_name}', '').strip()
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
    SERVICE FIRST: Save container configuration data through ConfigurationSaveService.

    Args:
        servers_data: List of server dictionaries from processed config

    Returns:
        Dict with container names as keys and success status as values
    """
    # SERVICE FIRST: Use Container Config Save Service for all file operations
    from services.config.container_config_save_service import get_container_config_save_service
    from services.config.server_config_service import get_server_config_service

    logger.info(f"[SAVE_DEBUG] save_container_configs_from_web called with {len(servers_data)} servers")

    results = {}
    config_save_service = get_container_config_save_service()
    server_config_service = get_server_config_service()

    # Get list of active containers from servers_data
    active_containers = set()
    for server in servers_data:
        container_name = server.get('docker_name') or server.get('container_name')
        if container_name:
            active_containers.add(container_name)

    # Get ALL existing containers from service (includes inactive ones)
    all_container_configs = server_config_service.get_all_servers()

    # Process ALL existing containers - mark inactive and preserve their structure
    for container_config in all_container_configs:
        container_name = container_config.get('container_name') or container_config.get('docker_name')

        if not container_name:
            continue

        # If this container is not in the active list, mark it as inactive
        if container_name not in active_containers:
            container_config['active'] = False
            # Preserve all other fields but ensure info structure exists
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

            # Save through service
            save_result = config_save_service.save_container_config(container_name, container_config)
            results[container_name] = save_result

            if save_result:
                logger.info(f"[SAVE_DEBUG] Marked {container_name} as inactive and preserved config")
            else:
                logger.error(f"Failed to save inactive state for {container_name}")

    # Now process the active containers
    for server in servers_data:
        container_name = server.get('docker_name') or server.get('container_name')
        if not container_name:
            logger.warning(f"Server data missing container name: {server}")
            continue

        try:
            # Get existing config from service or create new one
            existing_config = server_config_service.get_server_by_docker_name(container_name)
            container_config = existing_config if existing_config else {}

            # Update container config with server data
            container_config['container_name'] = container_name
            container_config['docker_name'] = container_name  # Required by status handlers
            container_config['name'] = container_name  # Alternative field for compatibility

            # IMPORTANT: Mark container as active (selected in Web UI)
            container_config['active'] = True  # This container was in selected_servers

            # Handle display_name - should be a single string for Web UI
            display_name_raw = server.get('display_name', container_name)

            # Debug logging to see what we're getting
            logger.info(f"[DISPLAY_NAME_DEBUG] Container: {container_name}, Raw display_name from server: {repr(display_name_raw)}, Type: {type(display_name_raw)}")

            # If it's a list (legacy format), take the first element
            if isinstance(display_name_raw, list):
                if len(display_name_raw) > 0:
                    display_name = str(display_name_raw[0])
                else:
                    display_name = container_name
            else:
                # It's already a string or something else, ensure it's a string
                display_name = str(display_name_raw) if display_name_raw else container_name

            container_config['display_name'] = display_name

            # Debug logging after setting display_name
            logger.info(f"[DISPLAY_NAME_DEBUG] Container: {container_name}, Final display_name being saved: {repr(display_name)}, Type: {type(display_name)}")

            # Set allowed_actions, ensuring it has at least 'status' if empty
            allowed_actions = server.get('allowed_actions', [])
            logger.info(f"[ALLOWED_ACTIONS_DEBUG] Container {container_name}: received allowed_actions from server data: {allowed_actions}")
            if not allowed_actions:
                allowed_actions = ['status']
                logger.warning(f"[ALLOWED_ACTIONS_DEBUG] Container {container_name}: allowed_actions was empty, defaulting to ['status']")
            container_config['allowed_actions'] = allowed_actions
            logger.info(f"[ALLOWED_ACTIONS_DEBUG] Container {container_name}: SAVING allowed_actions: {container_config['allowed_actions']}")

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

            # Save updated config through service
            save_result = config_save_service.save_container_config(container_name, container_config)
            results[container_name] = save_result

            if save_result:
                logger.info(f"[SAVE_DEBUG] Saved container config for {container_name}: actions={container_config.get('allowed_actions')}, display={container_config.get('display_name')}")
            else:
                logger.error(f"Failed to save container config for {container_name}")

        except Exception as e:
            logger.error(f"Error saving container config for {container_name}: {e}")
            results[container_name] = False

    return results