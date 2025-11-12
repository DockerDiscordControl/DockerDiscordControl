Usage Examples
==============

This page contains practical examples for common DDC operations.

Configuration Management
------------------------

Loading Configuration
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.config.config_service import get_config_service

   # Get the singleton config service instance
   config_service = get_config_service()

   # Load configuration (uses cache by default)
   config = config_service.get_config()

   # Access configuration values
   print(f"Language: {config['language']}")
   print(f"Timezone: {config['timezone']}")
   print(f"Guild ID: {config['guild_id']}")
   print(f"Servers: {len(config['servers'])} containers configured")

   # Force reload from disk (bypass cache)
   fresh_config = config_service.get_config(force_reload=True)

Token Encryption/Decryption
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.config.config_service import get_config_service
   from werkzeug.security import generate_password_hash

   config_service = get_config_service()

   # Step 1: Generate password hash (do this once during setup)
   password = "my-secure-password"
   password_hash = generate_password_hash(password)
   print(f"Password hash: {password_hash}")

   # Step 2: Encrypt Discord bot token
   plaintext_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTA.ABC123.xyz789-example"
   encrypted_token = config_service.encrypt_token(
       plaintext_token=plaintext_token,
       password_hash=password_hash
   )

   if encrypted_token:
       print(f"Encrypted token: {encrypted_token[:50]}...")
   else:
       print("Encryption failed!")

   # Step 3: Decrypt token
   decrypted_token = config_service.decrypt_token(
       encrypted_token=encrypted_token,
       password_hash=password_hash
   )

   if decrypted_token:
       print(f"Decrypted token: {decrypted_token[:20]}...")
       assert decrypted_token == plaintext_token
   else:
       print("Decryption failed!")

Working with Containers
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.config.config_service import get_config_service

   config_service = get_config_service()
   config = config_service.get_config()

   # Get all active containers
   servers = config.get('servers', [])
   print(f"Found {len(servers)} active containers:")

   for server in servers:
       container_name = server['container_name']
       display_name = server.get('display_name', container_name)
       allowed_actions = server.get('allowed_actions', [])
       order = server.get('order', 999)

       print(f"\n{order}. {display_name} ({container_name})")
       print(f"   Allowed actions: {', '.join(allowed_actions)}")

       # Check specific permissions
       can_start = 'start' in allowed_actions
       can_stop = 'stop' in allowed_actions
       can_restart = 'restart' in allowed_actions

       print(f"   Can start: {can_start}")
       print(f"   Can stop: {can_stop}")
       print(f"   Can restart: {can_restart}")

Working with Channels
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.config.config_service import get_config_service

   config_service = get_config_service()
   config = config_service.get_config()

   # Get channel permissions
   channel_permissions = config.get('channel_permissions', {})
   print(f"Configured channels: {len(channel_permissions)}")

   for channel_id, perms in channel_permissions.items():
       channel_name = perms.get('name', 'Unknown')
       commands = perms.get('commands', {})
       auto_refresh = perms.get('enable_auto_refresh', False)
       update_interval = perms.get('update_interval_minutes', 0)

       print(f"\nChannel: {channel_name} (ID: {channel_id})")
       print(f"  Commands enabled: {', '.join([k for k, v in commands.items() if v])}")
       print(f"  Auto-refresh: {auto_refresh}")

       if auto_refresh:
           print(f"  Update interval: {update_interval} minutes")

Error Handling
--------------

Using Custom Exceptions
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.config.config_service import get_config_service
   from services.exceptions import (
       ConfigServiceError,
       ConfigLoadError,
       ConfigCacheError,
       is_recoverable_error
   )

   config_service = get_config_service()

   try:
       config = config_service.get_config()
       print(f"Config loaded: {len(config)} keys")

   except ConfigLoadError as e:
       # Config file couldn't be loaded
       print(f"Failed to load config: {e.message}")
       print(f"Error code: {e.error_code}")
       print(f"Details: {e.details}")

       # Use default config as fallback
       config = get_default_config()

   except ConfigCacheError as e:
       # Cache error (non-critical)
       print(f"Cache error: {e.message}")

       # Retry without cache
       try:
           config = config_service.get_config(force_reload=True)
           print("Successfully loaded config after cache error")
       except Exception as retry_error:
           print(f"Retry failed: {retry_error}")
           raise

   except ConfigServiceError as e:
       # Generic config service error
       print(f"Config service error: {e.message}")
       raise

   except Exception as e:
       # Unexpected error
       print(f"Unexpected error: {e}")

       if is_recoverable_error(e):
           print("Error is recoverable - retrying...")
           # Implement retry logic
       else:
           print("Error is NOT recoverable")
           raise

Service-First Pattern
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.config.config_service import (
       get_config_service,
       GetConfigRequest,
       GetConfigResult
   )

   config_service = get_config_service()

   # Create request object
   request = GetConfigRequest(force_reload=True)

   # Call service method
   result: GetConfigResult = config_service.get_config_service(request)

   # Check result
   if result.success:
       config = result.config
       print(f"Config loaded: {len(config)} keys")
   else:
       print(f"Error: {result.error_message}")

Docker Operations
-----------------

Getting Container Status
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from app.utils.docker_utils import get_container_status_async
   import asyncio

   async def check_container():
       status = await get_container_status_async('nginx')

       if status:
           print(f"Container: {status['name']}")
           print(f"State: {status['state']}")
           print(f"Status: {status['status']}")
           print(f"Health: {status.get('health', 'N/A')}")
       else:
           print("Container not found or error occurred")

   # Run async function
   asyncio.run(check_container())

Performing Container Actions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from app.utils.docker_utils import execute_container_action_async
   import asyncio

   async def restart_container():
       result = await execute_container_action_async(
           container_name='nginx',
           action='restart'
       )

       if result['success']:
           print(f"Container restarted: {result['message']}")
       else:
           print(f"Error: {result.get('error', 'Unknown error')}")

   asyncio.run(restart_container())

Donation System
---------------

Checking Donation Status
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.donation.donation_service import get_donation_service

   donation_service = get_donation_service()

   # Get current power
   power = donation_service.get_current_power()
   print(f"Current power: ${power:.2f}")

   # Check if donations are enabled
   from services.config.config_service import get_config_service
   config = get_config_service().get_config()

   if config.get('donation_disable_key'):
       print("Donations are DISABLED (key present)")
   else:
       print("Donations are ENABLED")

Web UI Integration
------------------

Saving Configuration from Form
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.web.configuration_save_service import (
       get_configuration_save_service,
       ConfigurationSaveRequest
   )
   from flask import request

   @app.route('/save-config', methods=['POST'])
   def save_configuration():
       save_service = get_configuration_save_service()

       # Create save request
       save_request = ConfigurationSaveRequest(
           form_data=request.form,
           config_split_enabled=False
       )

       # Save configuration
       result = save_service.save_configuration(save_request)

       if result.success:
           return jsonify({
               'success': True,
               'message': result.message,
               'critical_changed': result.critical_settings_changed
           })
       else:
           return jsonify({
               'success': False,
               'error': result.error
           }), 500

Complete Example: Bot Setup
----------------------------

.. code-block:: python

   \"\"\"
   Complete example: Setting up DDC bot from scratch
   \"\"\"

   import asyncio
   from services.config.config_service import get_config_service
   from services.exceptions import ConfigLoadError
   from app.utils.docker_utils import get_container_status_async

   async def setup_bot():
       # Step 1: Load configuration
       try:
           config_service = get_config_service()
           config = config_service.get_config()
           print(f"✓ Configuration loaded")
       except ConfigLoadError as e:
           print(f"✗ Failed to load config: {e.message}")
           return

       # Step 2: Verify bot token
       bot_token = config.get('bot_token_decrypted_for_usage')
       if not bot_token:
           print("✗ No bot token found")
           return
       print(f"✓ Bot token found: {bot_token[:20]}...")

       # Step 3: Check guild ID
       guild_id = config.get('guild_id')
       if not guild_id:
           print("✗ No guild ID configured")
           return
       print(f"✓ Guild ID: {guild_id}")

       # Step 4: Verify container access
       servers = config.get('servers', [])
       if not servers:
           print("⚠ No containers configured")
       else:
           print(f"✓ {len(servers)} containers configured")

           # Test first container
           first_container = servers[0]['container_name']
           status = await get_container_status_async(first_container)

           if status:
               print(f"✓ Docker access working - {first_container}: {status['state']}")
           else:
               print(f"✗ Cannot access container: {first_container}")

       # Step 5: Verify channel permissions
       channels = config.get('channel_permissions', {})
       if not channels:
           print("⚠ No channels configured")
       else:
           print(f"✓ {len(channels)} channels configured")

       print("\n✓ Setup complete - ready to start bot!")

   if __name__ == '__main__':
       asyncio.run(setup_bot())

Testing
-------

Unit Testing Services
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import pytest
   from services.config.config_service import get_config_service
   from services.exceptions import ConfigLoadError

   class TestConfigService:
       \"\"\"Test cases for ConfigService.\"\"\"

       def test_get_config(self):
           \"\"\"Test configuration loading.\"\"\"
           config_service = get_config_service()
           config = config_service.get_config()

           assert isinstance(config, dict)
           assert 'language' in config
           assert 'timezone' in config
           assert 'servers' in config

       def test_token_encryption_decryption(self):
           \"\"\"Test token encryption/decryption cycle.\"\"\"
           config_service = get_config_service()

           password_hash = "test-hash"
           plaintext = "test-token"

           # Encrypt
           encrypted = config_service.encrypt_token(plaintext, password_hash)
           assert encrypted is not None
           assert encrypted != plaintext

           # Decrypt
           decrypted = config_service.decrypt_token(encrypted, password_hash)
           assert decrypted == plaintext

       def test_config_cache(self):
           \"\"\"Test configuration caching.\"\"\"
           config_service = get_config_service()

           # First load (from disk)
           config1 = config_service.get_config()

           # Second load (from cache)
           config2 = config_service.get_config()

           # Should be same data
           assert config1 == config2

           # Force reload
           config3 = config_service.get_config(force_reload=True)
           assert config3 is not None

Integration Testing
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import pytest
   import asyncio
   from services.config.config_service import get_config_service
   from app.utils.docker_utils import get_container_status_async

   @pytest.mark.asyncio
   async def test_full_workflow():
       \"\"\"Test complete workflow: config → Docker → action.\"\"\"

       # Load config
       config_service = get_config_service()
       config = config_service.get_config()
       assert config is not None

       # Get first configured container
       servers = config.get('servers', [])
       assert len(servers) > 0

       container_name = servers[0]['container_name']

       # Get container status
       status = await get_container_status_async(container_name)
       assert status is not None
       assert 'state' in status

       print(f"Container {container_name}: {status['state']}")

   if __name__ == '__main__':
       asyncio.run(test_full_workflow())
