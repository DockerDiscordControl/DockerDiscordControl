# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Import Utilities                               #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Zentrale Import-Utilities für häufig verwendete optionale Imports.
Eliminiert redundante try/except Import-Patterns im gesamten Projekt.
"""

import logging
from typing import Any, Optional, Tuple, Union
from utils.logging_utils import get_import_logger

logger = get_import_logger()

# Cache für bereits importierte Module
_import_cache = {}

def safe_import(module_name: str, fallback_value: Any = None, 
                cache_key: Optional[str] = None) -> Tuple[Any, bool]:
    """
    Sicherer Import mit Fallback-Wert und Caching.
    
    Args:
        module_name: Name des zu importierenden Moduls
        fallback_value: Wert bei fehlgeschlagenem Import
        cache_key: Optional cache key (default: module_name)
        
    Returns:
        Tuple von (imported_module_or_fallback, success_flag)
    """
    cache_key = cache_key or module_name
    
    # Prüfe Cache
    if cache_key in _import_cache:
        return _import_cache[cache_key]
    
    try:
        module = __import__(module_name)
        # Für verschachtelte Module (z.B. 'package.submodule')
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
    Sicherer Import eines spezifischen Items aus einem Modul.
    
    Args:
        module_name: Name des Moduls
        item_name: Name des zu importierenden Items
        fallback_value: Wert bei fehlgeschlagenem Import
        
    Returns:
        Tuple von (imported_item_or_fallback, success_flag)
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
    """Importiert ujson mit json als Fallback"""
    return safe_import('ujson', fallback_value=__import__('json'))

def import_uvloop() -> Tuple[Any, bool]:
    """Importiert uvloop für bessere async Performance"""
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
    """Importiert gevent für bessere Threading-Performance"""
    return safe_import('gevent')

def import_croniter() -> Tuple[Any, bool]:
    """Importiert croniter für Cron-Funktionalität"""
    return safe_import('croniter')

def import_docker() -> Tuple[Any, bool]:
    """Importiert Docker SDK"""
    return safe_import('docker')

def get_performance_imports() -> dict:
    """
    Sammelt alle Performance-relevanten Imports und gibt Status zurück.
    
    Returns:
        Dict mit Import-Status für Performance-Module
    """
    imports = {}
    
    # ujson für schnelleres JSON
    json_module, ujson_available = import_ujson()
    imports['ujson'] = {
        'available': ujson_available,
        'module': json_module,
        'description': 'Faster JSON processing'
    }
    
    # uvloop für bessere async Performance
    uvloop_module, uvloop_available = import_uvloop()
    imports['uvloop'] = {
        'available': uvloop_available,
        'module': uvloop_module,
        'description': 'Faster async event loop'
    }
    
    # gevent für bessere Threading
    gevent_module, gevent_available = import_gevent()
    imports['gevent'] = {
        'available': gevent_available,
        'module': gevent_module,
        'description': 'Better threading performance'
    }
    
    return imports

def log_performance_status():
    """Loggt den Status aller Performance-Optimierungen"""
    imports = get_performance_imports()
    
    logger.info("Performance optimization status:")
    for name, info in imports.items():
        status = "ENABLED" if info['available'] else "DISABLED"
        logger.info(f"  {name}: {status} - {info['description']}") 