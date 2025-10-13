# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Import Utilities                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Central import utilities for frequently used optional imports.
Eliminates redundant try/except import patterns throughout the project.
"""

import logging
from typing import Any, Optional, Tuple, Union
from utils.logging_utils import get_import_logger

logger = get_import_logger()

# Cache for already imported modules
_import_cache = {}

def safe_import(module_name: str, fallback_value: Any = None, 
                cache_key: Optional[str] = None) -> Tuple[Any, bool]:
    """
    Safe import with fallback value and caching.
    
    Args:
        module_name: Name of the module to import
        fallback_value: Value to use on failed import
        cache_key: Optional cache key (default: module_name)
        
    Returns:
        Tuple of (imported_module_or_fallback, success_flag)
    """
    cache_key = cache_key or module_name
    
    # Check cache
    if cache_key in _import_cache:
        return _import_cache[cache_key]
    
    try:
        module = __import__(module_name)
        # For nested modules (e.g. 'package.submodule')
        for component in module_name.split('.')[1:]:
            module = getattr(module, component)
        
        result = (module, True)
        _import_cache[cache_key] = result
        logger.debug(f"Successfully imported {module_name}")
        return result
    except ImportError as e:
        logger.debug(f"Failed to import {module_name}: {e}")
        result = (fallback_value, False)
        _import_cache[cache_key] = result
        return result

def safe_import_from(module_name: str, item_name: str, 
                     fallback_value: Any = None) -> Tuple[Any, bool]:
    """
    Safe import of a specific item from a module.

    Args:
        module_name: Name of the module
        item_name: Name of the item to import
        fallback_value: Value to use on failed import

    Returns:
        Tuple of (imported_item_or_fallback, success_flag)
    """
    cache_key = f"{module_name}.{item_name}"
    
    if cache_key in _import_cache:
        return _import_cache[cache_key]
    
    try:
        module = __import__(module_name, fromlist=[item_name])
        item = getattr(module, item_name)
        
        result = (item, True)
        _import_cache[cache_key] = result
        logger.debug(f"Successfully imported {item_name} from {module_name}")
        return result
    except (ImportError, AttributeError) as e:
        logger.debug(f"Failed to import {item_name} from {module_name}: {e}")
        result = (fallback_value, False)
        _import_cache[cache_key] = result
        return result

def import_ujson() -> Tuple[Any, bool]:
    """Imports ujson with json as fallback"""
    return safe_import('ujson', fallback_value=__import__('json'))

def import_uvloop() -> Tuple[Any, bool]:
    """Imports uvloop for better async performance"""
    uvloop, success = safe_import('uvloop')
    if success:
        try:
            uvloop.install()
            logger.info("uvloop installed for better async performance")
        except Exception as e:
            logger.warning(f"Failed to install uvloop: {e}")
            success = False
    return uvloop, success

def import_gevent() -> Tuple[Any, bool]:
    """Imports gevent for better threading performance"""
    return safe_import('gevent')

def import_croniter() -> Tuple[Any, bool]:
    """Imports croniter for cron functionality"""
    return safe_import('croniter')

def import_docker() -> Tuple[Any, bool]:
    """Imports Docker SDK"""
    return safe_import('docker')

def get_performance_imports() -> dict:
    """
    Collects all performance-relevant imports and returns status.
    
    Returns:
        Dict with import status for performance modules
    """
    imports = {}
    
    # ujson for faster JSON
    json_module, ujson_available = import_ujson()
    imports['ujson'] = {
        'available': ujson_available,
        'module': json_module,
        'description': 'Faster JSON processing'
    }
    
    # uvloop for better async performance
    uvloop_module, uvloop_available = import_uvloop()
    imports['uvloop'] = {
        'available': uvloop_available,
        'module': uvloop_module,
        'description': 'Faster async event loop'
    }
    
    # gevent for better threading
    gevent_module, gevent_available = import_gevent()
    imports['gevent'] = {
        'available': gevent_available,
        'module': gevent_module,
        'description': 'Better threading performance'
    }
    
    return imports

def log_performance_status():
    """Logs the status of all performance optimizations"""
    imports = get_performance_imports()
    
    logger.info("Performance optimization status:")
    for name, info in imports.items():
        status = "ENABLED" if info['available'] else "DISABLED"
        logger.info(f"  {name}: {status} - {info['description']}") 