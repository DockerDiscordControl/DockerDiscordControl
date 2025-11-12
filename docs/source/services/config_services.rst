Configuration Services
======================

The configuration services provide centralized configuration management for DDC.
All configuration-related operations go through these services.

ConfigService
-------------

.. autoclass:: services.config.config_service.ConfigService
   :members:
   :undoc-members:
   :show-inheritance:
   :special-members: __init__

Main Configuration Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``ConfigService`` is the central hub for all configuration operations.

**Key Features:**

* Unified configuration loading from multiple sources
* Token encryption/decryption with PBKDF2
* Thread-safe operations with locks
* Configuration caching with invalidation
* Legacy compatibility layer

**Usage Example:**

.. code-block:: python

   from services.config.config_service import get_config_service

   # Get singleton instance
   config_service = get_config_service()

   # Load configuration
   config = config_service.get_config()
   print(f"Guild ID: {config['guild_id']}")
   print(f"Language: {config['language']}")
   print(f"Servers: {len(config['servers'])} containers")

   # Encrypt a Discord bot token
   password_hash = generate_password_hash("my-password")
   encrypted_token = config_service.encrypt_token(
       plaintext_token="MTIzNDU2Nzg5MDEyMzQ1Njc4OTA.ABC123.xyz789",
       password_hash=password_hash
   )

   # Decrypt token
   decrypted_token = config_service.decrypt_token(
       encrypted_token=encrypted_token,
       password_hash=password_hash
   )

   # Save configuration
   from services.config.config_service import ConfigServiceResult
   result = config_service.save_config(config)
   if result.success:
       print("Configuration saved successfully")
   else:
       print(f"Error: {result.error}")

Configuration Loading
~~~~~~~~~~~~~~~~~~~~~

``get_config()`` loads configuration from multiple sources:

.. code-block:: python

   # Load with default caching
   config = config_service.get_config()

   # Force reload from disk (bypass cache)
   config = config_service.get_config(force_reload=True)

Configuration structure:

.. code-block:: python

   {
       # System settings
       'language': 'de',
       'timezone': 'Europe/Berlin',
       'guild_id': '1234567890',

       # Authentication
       'bot_token': 'encrypted-token-here',
       'web_ui_user': 'admin',
       'web_ui_password_hash': 'hashed-password',

       # Docker settings
       'docker_socket_path': '/var/run/docker.sock',
       'container_command_cooldown': 5,
       'docker_api_timeout': 30,

       # Containers (loaded from config/containers/*.json)
       'servers': [
           {
               'container_name': 'nginx',
               'display_name': 'Nginx Web Server',
               'allowed_actions': ['status', 'start', 'stop', 'restart'],
               'active': True,
               'order': 1
           }
       ],

       # Channels (loaded from config/channels/*.json)
       'channel_permissions': {
           '1234567890': {
               'name': 'status-channel',
               'commands': {'serverstatus': True, 'control': False},
               'enable_auto_refresh': True,
               'update_interval_minutes': 5
           }
       }
   }

Token Encryption
~~~~~~~~~~~~~~~~

DDC uses Fernet encryption with PBKDF2 key derivation:

.. code-block:: python

   from werkzeug.security import generate_password_hash

   # Generate password hash (do this once)
   password_hash = generate_password_hash("your-secure-password")

   # Encrypt Discord bot token
   plaintext_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTA.ABC123.xyz789"
   encrypted = config_service.encrypt_token(
       plaintext_token=plaintext_token,
       password_hash=password_hash
   )
   # Returns: Base64-encoded encrypted token

   # Decrypt token (automatically used when loading config)
   decrypted = config_service.decrypt_token(
       encrypted_token=encrypted,
       password_hash=password_hash
   )
   # Returns: Original plaintext token

**Security Notes:**

* Tokens are encrypted using Fernet (AES-128 in CBC mode)
* Key is derived from password hash using PBKDF2-HMAC-SHA256
* 260,000 iterations for key derivation
* Token cache is encrypted in memory

ConfigLoaderService
-------------------

.. autoclass:: services.config.config_loader_service.ConfigLoaderService
   :members:
   :show-inheritance:

Handles all configuration loading operations.

**Features:**

* Real modular structure (individual files per container/channel)
* Virtual modular structure (legacy files)
* Automatic structure detection
* Container filtering (active/inactive)

**Usage Example:**

.. code-block:: python

   loader_service = ConfigLoaderService(
       config_dir=Path('config'),
       channels_dir=Path('config/channels'),
       containers_dir=Path('config/containers'),
       # ... other parameters
   )

   # Check structure type
   if loader_service.has_real_modular_structure():
       config = loader_service.load_real_modular_config()
   else:
       config = loader_service.load_virtual_modular_config()

   # Load containers
   servers = loader_service.load_all_containers_from_files()
   # Only active containers are loaded

   # Load channels
   channel_data = loader_service.load_all_channels_from_files()

ConfigMigrationService
----------------------

.. autoclass:: services.config.config_migration_service.ConfigMigrationService
   :members:
   :show-inheritance:

Handles configuration migration between versions.

**Features:**

* v1.1.x → v2.0 migration
* Legacy config detection
* Modular structure creation
* Backup support

ConfigValidationService
-----------------------

.. autoclass:: services.config.config_validation_service.ConfigValidationService
   :members:
   :show-inheritance:

Validates configuration data.

**Features:**

* Discord token validation
* Config structure validation
* Default value provision

ConfigCacheService
------------------

.. autoclass:: services.config.config_cache_service.ConfigCacheService
   :members:
   :show-inheritance:

Manages configuration caching.

**Features:**

* File-based cache with modification time checking
* Token caching (encrypted in memory)
* Cache invalidation
* Thread-safe operations

**Usage Example:**

.. code-block:: python

   cache_service = ConfigCacheService()

   # Get cached config (returns None if expired)
   cached = cache_service.get_cached_config('unified', config_dir)

   # Set cache
   cache_service.set_cached_config('unified', config, config_dir)

   # Invalidate all caches
   cache_service.invalidate_cache()

ConfigFormParserService
-----------------------

.. autoclass:: services.config.config_form_parser_service.ConfigFormParserService
   :members:
   :show-inheritance:

Parses web form data into configuration structures.

**Usage Example:**

.. code-block:: python

   # Parse server configurations from web form
   servers = ConfigFormParserService.parse_servers_from_form(form_data)

   # Parse channel permissions
   channels = ConfigFormParserService.parse_channel_permissions_from_form(form_data)

   # Process complete form
   updated_config, success, message = ConfigFormParserService.process_config_form(
       form_data=request.form,
       current_config=current_config,
       config_service=get_config_service()
   )

Request/Result Classes
----------------------

GetConfigRequest
~~~~~~~~~~~~~~~~

.. autoclass:: services.config.config_service.GetConfigRequest
   :members:

GetConfigResult
~~~~~~~~~~~~~~~

.. autoclass:: services.config.config_service.GetConfigResult
   :members:

ConfigServiceResult
~~~~~~~~~~~~~~~~~~~

.. autoclass:: services.config.config_service.ConfigServiceResult
   :members:

Factory Functions
-----------------

.. autofunction:: services.config.config_service.get_config_service

.. autofunction:: services.config.config_service.load_config

.. autofunction:: services.config.config_service.save_config
