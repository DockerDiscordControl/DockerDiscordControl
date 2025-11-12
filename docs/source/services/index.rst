Services API Reference
======================

This section documents all DDC services and their APIs.

.. toctree::
   :maxdepth: 2

   config_services
   docker_services
   donation_services
   mech_services
   web_services

Overview
--------

DDC uses a **service-oriented architecture** where each service has a single responsibility.
All services follow consistent patterns:

* **Request/Result Pattern**: Services use dataclasses for input/output
* **Error Handling**: Custom exceptions with structured error data
* **Singleton Pattern**: Services are typically singletons
* **Dependency Injection**: Services receive dependencies via constructor

Service Patterns
----------------

Request/Result Pattern
~~~~~~~~~~~~~~~~~~~~~~

All services use typed request/result objects:

.. code-block:: python

   from dataclasses import dataclass
   from typing import Optional, Any

   @dataclass(frozen=True)
   class GetConfigRequest:
       """Request to get configuration."""
       force_reload: bool = False

   @dataclass(frozen=True)
   class GetConfigResult:
       """Result containing configuration data."""
       success: bool
       config: Optional[Dict[str, Any]] = None
       error_message: Optional[str] = None

   # Usage
   request = GetConfigRequest(force_reload=True)
   result = config_service.get_config_service(request)
   if result.success:
       config = result.config
   else:
       print(f"Error: {result.error_message}")

Exception Handling
~~~~~~~~~~~~~~~~~~

Services raise domain-specific exceptions:

.. code-block:: python

   from services.exceptions import ConfigServiceError, ConfigLoadError

   try:
       config = config_service.get_config()
   except ConfigLoadError as e:
       logger.error(f"Failed to load config: {e.message}", exc_info=True)
       # Handle error or use defaults
       config = get_default_config()
   except ConfigCacheError as e:
       logger.warning(f"Cache error: {e.message}")
       # Retry without cache
       config = config_service.get_config(force_reload=True)

See :doc:`../error_handling` for complete exception hierarchy.

Singleton Pattern
~~~~~~~~~~~~~~~~~

Most services are singletons accessed via factory functions:

.. code-block:: python

   from services.config.config_service import get_config_service

   # Get singleton instance
   config_service = get_config_service()

   # Multiple calls return same instance
   assert config_service is get_config_service()

Dependency Injection
~~~~~~~~~~~~~~~~~~~~

Services receive dependencies via constructor:

.. code-block:: python

   class ConfigLoaderService:
       def __init__(self, config_dir: Path, channels_dir: Path,
                    load_json_func, validation_service):
           self.config_dir = config_dir
           self.channels_dir = channels_dir
           self._load_json_file = load_json_func
           self._validation_service = validation_service

Service Guidelines
------------------

When creating new services, follow these guidelines:

1. **Single Responsibility**: Each service does one thing well
2. **Typed Interfaces**: Use dataclasses for request/result
3. **Custom Exceptions**: Define domain-specific exceptions
4. **Comprehensive Logging**: Log all operations with appropriate levels
5. **Thread Safety**: Use locks for shared state
6. **Documentation**: Complete docstrings with examples
7. **Testing**: Unit tests for all public methods
