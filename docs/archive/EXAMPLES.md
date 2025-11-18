# DDC Code Examples

Practical code examples for common DDC operations.

## Configuration Examples

### Load Configuration

```python
from services.config.config_service import get_config_service

config_service = get_config_service()
config = config_service.get_config()

print(f"Language: {config['language']}")
print(f"Timezone: {config['timezone']}")
print(f"Servers: {len(config['servers'])} containers")
```

### Token Encryption/Decryption

```python
from services.config.config_service import get_config_service
from werkzeug.security import generate_password_hash

config_service = get_config_service()

# Generate password hash (once)
password_hash = generate_password_hash("my-password")

# Encrypt token
encrypted = config_service.encrypt_token(
    plaintext_token="MTIzNDU2.ABC.xyz",
    password_hash=password_hash
)

# Decrypt token
decrypted = config_service.decrypt_token(
    encrypted_token=encrypted,
    password_hash=password_hash
)
```

### Work with Containers

```python
config = config_service.get_config()
servers = config.get('servers', [])

for server in servers:
    name = server['container_name']
    display = server.get('display_name', name)
    actions = server.get('allowed_actions', [])

    print(f"{display}: {', '.join(actions)}")

    # Check permissions
    can_start = 'start' in actions
    can_stop = 'stop' in actions
```

## Docker Examples

### Get Container Status

```python
import asyncio
from app.utils.docker_utils import get_container_status_async

async def check_status():
    status = await get_container_status_async('nginx')

    if status:
        print(f"Container: {status['name']}")
        print(f"State: {status['state']}")
        print(f"Status: {status['status']}")

asyncio.run(check_status())
```

### Perform Container Action

```python
import asyncio
from app.utils.docker_utils import execute_container_action_async

async def restart_container():
    result = await execute_container_action_async(
        container_name='nginx',
        action='restart'
    )

    if result['success']:
        print(f"Success: {result['message']}")
    else:
        print(f"Error: {result.get('error')}")

asyncio.run(restart_container())
```

## Error Handling Examples

### Basic Exception Handling

```python
from services.exceptions import ConfigServiceError, ConfigLoadError

try:
    config = config_service.get_config()
except ConfigLoadError as e:
    print(f"Config load error: {e.message}")
    print(f"Error code: {e.error_code}")
    config = get_default_config()
except ConfigServiceError as e:
    print(f"Config service error: {e.message}")
    raise
```

### Retry with Fallback

```python
from services.exceptions import ConfigCacheError

try:
    config = config_service.get_config()
except ConfigCacheError as e:
    print(f"Cache error: {e.message}")
    # Retry without cache
    config = config_service.get_config(force_reload=True)
```

## Web UI Examples

### Save Configuration

```python
from services.web.configuration_save_service import (
    get_configuration_save_service,
    ConfigurationSaveRequest
)
from flask import request

save_service = get_configuration_save_service()
save_request = ConfigurationSaveRequest(form_data=request.form)
result = save_service.save_configuration(save_request)

if result.success:
    print(f"Saved: {result.message}")
    if result.critical_settings_changed:
        print("Caches invalidated")
```

## Testing Examples

### Unit Test

```python
import pytest
from services.config.config_service import get_config_service

def test_get_config():
    config_service = get_config_service()
    config = config_service.get_config()

    assert isinstance(config, dict)
    assert 'language' in config
    assert 'servers' in config
```

### Integration Test

```python
import pytest
import asyncio
from app.utils.docker_utils import get_container_status_async

@pytest.mark.asyncio
async def test_docker_status():
    from services.config.config_service import get_config_service

    config = get_config_service().get_config()
    servers = config.get('servers', [])
    assert len(servers) > 0

    container = servers[0]['container_name']
    status = await get_container_status_async(container)

    assert status is not None
    assert 'state' in status
```

## Complete Workflow Example

```python
\"\"\"
Complete example: Bot setup workflow
\"\"\"

import asyncio
from services.config.config_service import get_config_service
from services.exceptions import ConfigLoadError
from app.utils.docker_utils import get_container_status_async

async def setup_bot():
    # Load config
    try:
        config_service = get_config_service()
        config = config_service.get_config()
        print("✓ Config loaded")
    except ConfigLoadError as e:
        print(f"✗ Config load failed: {e.message}")
        return

    # Check token
    token = config.get('bot_token_decrypted_for_usage')
    if not token:
        print("✗ No bot token")
        return
    print(f"✓ Bot token: {token[:20]}...")

    # Check guild
    guild_id = config.get('guild_id')
    if not guild_id:
        print("✗ No guild ID")
        return
    print(f"✓ Guild ID: {guild_id}")

    # Check containers
    servers = config.get('servers', [])
    if not servers:
        print("⚠ No containers configured")
    else:
        print(f"✓ {len(servers)} containers")

        # Test Docker access
        container = servers[0]['container_name']
        status = await get_container_status_async(container)

        if status:
            print(f"✓ Docker OK - {container}: {status['state']}")
        else:
            print(f"✗ Docker access failed")

    # Check channels
    channels = config.get('channel_permissions', {})
    if not channels:
        print("⚠ No channels configured")
    else:
        print(f"✓ {len(channels)} channels")

    print("\n✓ Setup complete!")

if __name__ == '__main__':
    asyncio.run(setup_bot())
```

## See Also

- [SERVICES.md](SERVICES.md) - Service architecture
- [CONFIGURATION.md](CONFIGURATION.md) - Configuration guide
- [ERROR_HANDLING.md](ERROR_HANDLING.md) - Exception handling
