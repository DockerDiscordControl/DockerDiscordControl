# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Common Helpers                                 #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Common utility functions for the entire project.
Eliminates redundant code between different modules.
"""

from typing import Dict, Any, List, Optional, Union, Tuple
import asyncio
from utils.logging_utils import get_module_logger
from utils.time_utils import get_datetime_imports, format_duration

import requests
import socket

# Central datetime imports
datetime, timedelta, timezone, time = get_datetime_imports()

# Logger with central utility
logger = get_module_logger('common_helpers')

def hash_container_data(container_data: Dict[str, Any]) -> Union[int, float]:
    """
    Creates a hash of container data to detect changes.
    
    Args:
        container_data: Dictionary containing container information
        
    Returns:
        Hash value or timestamp on error
    """
    try:
        # Create a hash from relevant fields
        hash_input = f"{container_data.get('id', '')}-{container_data.get('status', '')}-{container_data.get('image', '')}"
        return hash(hash_input)
    except Exception:
        # In case of errors, return a timestamp, which leads to reevaluation
        return time.time()

def safe_get_nested(data: Dict[str, Any], keys: str, default: Any = None) -> Any:
    """
    Safely gets a nested value from a dictionary using dot notation.
    
    Args:
        data: Dictionary to search in
        keys: Dot-separated key path (e.g., 'server.config.name')
        default: Default value if key not found
        
    Returns:
        Value at the key path or default
    """
    try:
        result = data
        for key in keys.split('.'):
            if isinstance(result, dict) and key in result:
                result = result[key]
            else:
                return default
        return result
    except (KeyError, TypeError, AttributeError):
        return default

def format_uptime(uptime_seconds: Optional[float]) -> str:
    """
    Formats uptime seconds into a human-readable string.
    
    Args:
        uptime_seconds: Uptime in seconds
        
    Returns:
        Formatted uptime string
    """
    if uptime_seconds is None or uptime_seconds < 0:
        return "Unknown"
    
    try:
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    except (ValueError, TypeError):
        return "Unknown"

def format_memory(memory_bytes: Optional[Union[int, float]]) -> str:
    """
    Formats memory bytes into a human-readable string.
    
    Args:
        memory_bytes: Memory in bytes
        
    Returns:
        Formatted memory string
    """
    if memory_bytes is None or memory_bytes < 0:
        return "Unknown"
    
    try:
        memory_bytes = float(memory_bytes)
        
        # Convert to appropriate unit
        if memory_bytes >= 1024**3:  # GB
            return f"{memory_bytes / (1024**3):.1f} GB"
        elif memory_bytes >= 1024**2:  # MB
            return f"{memory_bytes / (1024**2):.1f} MB"
        elif memory_bytes >= 1024:  # KB
            return f"{memory_bytes / 1024:.1f} KB"
        else:
            return f"{int(memory_bytes)} B"
    except (ValueError, TypeError):
        return "Unknown"

def format_cpu_percentage(cpu_percent: Optional[Union[int, float]]) -> str:
    """
    Formats CPU percentage with consistent formatting.
    
    Args:
        cpu_percent: CPU percentage
        
    Returns:
        Formatted CPU percentage string
    """
    if cpu_percent is None:
        return "Unknown"
    
    try:
        cpu_percent = float(cpu_percent)
        return f"{cpu_percent:.1f}%"
    except (ValueError, TypeError):
        return "Unknown"

def truncate_string(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncates a string to a maximum length with optional suffix.
    
    Args:
        text: String to truncate
        max_length: Maximum length including suffix
        suffix: Suffix to add when truncating
        
    Returns:
        Truncated string
    """
    if not isinstance(text, str):
        text = str(text)
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix

def validate_container_name(name: str) -> bool:
    """
    Validate Docker container name format.
    
    Args:
        name: Container name to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    # Make sure name follows Docker naming conventions
    if not name or not isinstance(name, str):
        return False
    
    # Allow alphanumeric characters, hyphens, underscores, and dots
    import re
    pattern = r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$'
    
    # eXamine name against pattern and length constraints
    if not re.match(pattern, name):
        return False
        
    # Docker container names must be 1-63 characters
    if len(name) < 1 or len(name) > 63:
        return False
        
    # Docker names cannot start with hyphen or dot
    if name.startswith('-') or name.startswith('.'):
        return False
        
    # Container names are valid if they pass all checks
    return True

def get_current_timestamp() -> str:
    """
    Gets current timestamp in ISO format with timezone.
    
    Returns:
        ISO formatted timestamp string
    """
    return datetime.now(timezone.utc).isoformat()

def parse_boolean(value: Any, default: bool = False) -> bool:
    """
    Safely parses a value to boolean.
    
    Args:
        value: Value to parse
        default: Default value if parsing fails
        
    Returns:
        Boolean value
    """
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on', 'enabled')
    
    if isinstance(value, (int, float)):
        return bool(value)
    
    return default

def sanitize_log_message(message: str) -> str:
    """
    Sanitizes a log message by removing sensitive information.
    
    Args:
        message: Log message to sanitize
        
    Returns:
        Sanitized log message
    """
    if not isinstance(message, str):
        message = str(message)
    
    # Remove potential sensitive patterns
    import re
    
    # Remove tokens, passwords, keys
    message = re.sub(r'(token|password|key|secret)[:=]\s*[^\s]+', r'\1=***', message, flags=re.IGNORECASE)
    
    # Remove potential API keys
    message = re.sub(r'\b[A-Za-z0-9]{32,}\b', '***', message)
    
    return message

def is_valid_ip(ip: str) -> bool:
    """Basic IP validation."""
    try:
        socket.inet_aton(ip)
        return True
    except socket.error:
        return False

async def get_wan_ip_async() -> Optional[str]:
    """
    Async version of WAN IP detection using aiohttp.
    
    Returns:
        WAN IP address as string or None if detection fails
    """
    import aiohttp
    
    services = [
        'https://api.ipify.org',
        'https://ifconfig.me/ip', 
        'https://icanhazip.com'
    ]
    
    timeout = aiohttp.ClientTimeout(total=5.0)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for service in services:
                try:
                    async with session.get(service) as response:
                        if response.status == 200:
                            ip = (await response.text()).strip()
                            if is_valid_ip(ip):
                                return ip
                except Exception as e:
                    logger.debug(f"Service {service} failed: {e}")
                    continue
                    
    except Exception as e:
        logger.debug(f"WAN IP detection failed: {e}")
        
    return None

def validate_ip_format(ip_string: str) -> bool:
    """
    Basic validation for IP/domain format.
    
    Args:
        ip_string: IP address, domain, or hostname (with optional port)
        
    Returns:
        bool: True if format is valid, False otherwise
    """
    if not ip_string:
        return True  # Empty is valid
    
    # Allow domain names, IPs, with optional port
    import re
    pattern = re.compile(r'^([a-zA-Z0-9.-]+|localhost)(?::\d{1,5})?$')
    return bool(pattern.match(ip_string))

def batch_process(items: List[Any], batch_size: int = 10) -> List[List[Any]]:
    """
    Splits a list into batches of specified size.
    
    Args:
        items: List of items to batch
        batch_size: Size of each batch
        
    Returns:
        List of batches
    """
    if not items or batch_size <= 0:
        return []
    
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

def deep_merge_dicts(dict1: Dict[str, Any], dict2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merges two dictionaries.
    
    Args:
        dict1: First dictionary
        dict2: Second dictionary (takes precedence)
        
    Returns:
        Merged dictionary
    """
    result = dict1.copy()
    
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    
    return result

def retry_on_exception(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Decorator for retrying functions on exception.
    
    Args:
        max_retries: Maximum number of retries
        delay: Initial delay between retries
        backoff: Backoff multiplier for delay
        
    Returns:
        Decorator function
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {current_delay}s...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed for {func.__name__}")
                        
            raise last_exception
        return wrapper
    return decorator

def async_retry_with_backoff(max_retries=3, initial_delay=1.0, backoff=2.0):
    """
    Async version of retry_with_backoff decorator that uses asyncio.sleep.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            current_delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    if asyncio.iscoroutinefunction(func):
                        return await func(*args, **kwargs)
                    else:
                        return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}. Retrying in {current_delay}s...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"All {max_retries + 1} attempts failed for {func.__name__}")
                        
            raise last_exception
        return wrapper
    return decorator 

def get_public_ip() -> Optional[str]:
    """
    Get the public/external IP address of the server.
    
    Returns:
        str: Public IP address or None if detection fails
    """
    try:
        # Try multiple services for reliability
        services = [
            'https://api.ipify.org',
            'https://ifconfig.me',
            'https://icanhazip.com'
        ]
        
        for service in services:
            try:
                response = requests.get(service, timeout=5)
                if response.status_code == 200:
                    ip = response.text.strip()
                    # Basic IP validation
                    if _is_valid_ip(ip):
                        return ip
            except Exception as e:
                logger.debug(f"Failed to get IP from {service}: {e}")
                continue
                
        logger.warning("Failed to detect public IP from all services")
        return None
        
    except Exception as e:
        logger.error(f"Error detecting public IP: {e}")
        return None

def _is_valid_ip(ip: str) -> bool:
    """
    Validate if a string is a valid IP address.
    
    Args:
        ip: IP address string to validate
        
    Returns:
        bool: True if valid IP address
    """
    try:
        socket.inet_aton(ip)
        return True
    except socket.error:
        return False

def validate_container_info_text(text: str) -> bool:
    """
    Validate container info text meets requirements.
    
    Args:
        text: Info text to validate
        
    Returns:
        bool: True if valid (within 250 character limit)
    """
    return len(text) <= 250 