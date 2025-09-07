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