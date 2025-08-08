# -*- coding: utf-8 -*-
"""
Web UI handler for container info - saves to separate JSON files
"""

import logging
from typing import Dict, Any
from utils.container_info_manager import get_container_info_manager
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
    info_manager = get_container_info_manager()
    results = {}
    
    for container_name in container_names:
        try:
            # Extract info data for this container
            info_data = {
                'enabled': form_data.get(f'info_enabled_{container_name}', '0') == '1',
                'show_ip': form_data.get(f'info_show_ip_{container_name}', '0') == '1',
                'custom_ip': form_data.get(f'info_custom_ip_{container_name}', '').strip(),
                'custom_text': form_data.get(f'info_custom_text_{container_name}', '').strip()
            }
            
            # Save to JSON file
            success = info_manager.save_container_info(container_name, info_data)
            results[container_name] = success
            
            if success:
                logger.info(f"Saved container info for {container_name} from Web UI")
            else:
                logger.error(f"Failed to save container info for {container_name} from Web UI")
                
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
    info_manager = get_container_info_manager()
    results = {}
    
    for container_name in container_names:
        try:
            info_data = info_manager.load_container_info(container_name)
            results[container_name] = info_data
            logger.debug(f"Loaded container info for {container_name}: {info_data}")
        except Exception as e:
            logger.error(f"Error loading container info for {container_name}: {e}")
            results[container_name] = {
                'enabled': False,
                'show_ip': False,
                'custom_ip': '',
                'custom_text': ''
            }
    
    return results