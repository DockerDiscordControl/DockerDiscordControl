# DDC Configuration Guide

Complete guide to DockerDiscordControl configuration.

## Table of Contents

- [Configuration Files](#configuration-files)
- [Loading Configuration](#loading-configuration)
- [Configuration Structure](#configuration-structure)
- [Container Configuration](#container-configuration)
- [Channel Configuration](#channel-configuration)
- [Token Encryption](#token-encryption)
- [Advanced Settings](#advanced-settings)

## Configuration Files

DDC uses a **modular configuration structure** with individual files for different components.

### File Structure

```
config/
├── config.json              # Main system settings
├── auth.json                # Authentication settings
├── heartbeat.json           # Heartbeat configuration
├── web_ui.json             # Web UI settings
├── docker_settings.json    # Docker daemon settings
├── containers/             # Individual container configs
│   ├── nginx.json
│   ├── plex.json
│   └── minecraft.json
└── channels/               # Individual channel configs
    ├── status-channel.json
    ├── control-channel.json
    └── default.json
```

### Legacy Compatibility

DDC also supports legacy v1.x config files:
- `bot_config.json` (migrated to config.json + auth.json + heartbeat.json)
- `docker_config.json` (migrated to docker_settings.json + containers/)
- `web_config.json` (migrated to web_ui.json)
- `channels_config.json` (migrated to channels/)

## Loading Configuration

### Basic Loading

```python
from services.config.config_service import get_config_service

# Get the config service singleton
config_service = get_config_service()

# Load configuration (uses cache by default)
config = config_service.get_config()

# Access configuration values
language = config['language']  # 'de'
timezone = config['timezone']  # 'Europe/Berlin'
guild_id = config['guild_id']  # '1234567890'
```

### Force Reload (Bypass Cache)

```python
# Force reload from disk
fresh_config = config_service.get_config(force_reload=True)
```

### Using Legacy Functions

```python
from services.config.config_service import load_config, save_config

# Load config (legacy compatibility)
config = load_config()

# Save config (legacy compatibility)
success = save_config(config)
```

## Configuration Structure

Complete configuration dictionary structure:

```python
{
    # System Settings
    'language': 'de',                    # Language code ('de', 'en')
    'timezone': 'Europe/Berlin',         # Timezone string
    'guild_id': '1234567890',           # Discord guild ID

    # Authentication
    'bot_token': 'encrypted-token',      # Encrypted Discord bot token
    'web_ui_user': 'admin',             # Web UI username
    'web_ui_password_hash': 'hash...',   # Hashed password
    'admin_enabled': True,               # Admin features enabled

    # Heartbeat
    'heartbeat_channel_id': '9876543210', # Heartbeat channel ID

    # Docker Settings
    'docker_socket_path': '/var/run/docker.sock',
    'container_command_cooldown': 5,     # Cooldown in seconds
    'docker_api_timeout': 30,            # API timeout in seconds
    'max_log_lines': 50,                 # Max log lines to fetch

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
            'commands': {
                'serverstatus': True,
                'ss': True,
                'control': False,
                'schedule': False,
                'info': False
            },
            'post_initial': True,
            'enable_auto_refresh': True,
            'update_interval_minutes': 5,
            'recreate_messages_on_inactivity': True,
            'inactivity_timeout_minutes': 60
        }
    },

    # Default Channel Permissions
    'default_channel_permissions': {
        'commands': {
            'serverstatus': False,
            'control': False,
            'schedule': False,
            'info': False
        }
    },

    # Advanced Settings
    'session_timeout': 3600,             # Web UI session timeout
    'donation_disable_key': '',          # Donation disable key
    'scheduler_debug_mode': False,       # Scheduler debug logging
    'advanced_settings': {}              # Additional advanced settings
}
```

## Container Configuration

### Individual Container Files

Each container has its own JSON file in `config/containers/`:

**config/containers/nginx.json**:

```json
{
  "container_name": "nginx",
  "display_name": "Nginx Web Server",
  "docker_name": "nginx",
  "allowed_actions": ["status", "start", "stop", "restart"],
  "active": true,
  "order": 1,
  "info": {
    "enabled": true,
    "show_ip": true,
    "custom_ip": "192.168.1.100",
    "custom_port": "8080",
    "custom_text": "Public web server"
  }
}
```

### Container Fields

| Field | Type | Description |
|-------|------|-------------|
| `container_name` | string | Docker container name (must match actual container) |
| `display_name` | string | Name shown in Discord |
| `docker_name` | string | Docker name (usually same as container_name) |
| `allowed_actions` | array | Allowed actions: status, start, stop, restart |
| `active` | boolean | Whether container appears in Discord (true/false) |
| `order` | number | Display order (lower numbers first) |
| `info` | object | Container info configuration |

### Info Configuration

```json
{
  "info": {
    "enabled": true,              // Enable info command for this container
    "show_ip": true,              // Show IP address
    "custom_ip": "192.168.1.100", // Custom IP (optional, overrides auto-detect)
    "custom_port": "25565",       // Custom port (optional)
    "custom_text": "Minecraft Server - Join now!" // Custom text (optional)
  }
}
```

### Working with Containers

```python
from services.config.config_service import get_config_service

config = get_config_service().get_config()

# Get all active containers
servers = config.get('servers', [])

for server in servers:
    container_name = server['container_name']
    display_name = server.get('display_name', container_name)
    allowed_actions = server.get('allowed_actions', [])
    active = server.get('active', False)
    order = server.get('order', 999)

    print(f"{order}. {display_name} ({container_name})")
    print(f"   Active: {active}")
    print(f"   Allowed: {', '.join(allowed_actions)}")

    # Check specific permissions
    can_start = 'start' in allowed_actions
    can_stop = 'stop' in allowed_actions
    can_restart = 'restart' in allowed_actions

    if can_start:
        print(f"   ✓ Can start container")
    if can_stop:
        print(f"   ✓ Can stop container")
    if can_restart:
        print(f"   ✓ Can restart container")
```

### Adding a New Container

1. Create file: `config/containers/mycontainer.json`
2. Configure permissions:

```json
{
  "container_name": "mycontainer",
  "display_name": "My Container",
  "docker_name": "mycontainer",
  "allowed_actions": ["status", "start", "stop", "restart"],
  "active": true,
  "order": 10
}
```

3. Reload configuration or restart bot

## Channel Configuration

### Individual Channel Files

Each channel has its own JSON file in `config/channels/`:

**config/channels/status-channel.json**:

```json
{
  "channel_id": "1234567890",
  "name": "status-channel",
  "commands": {
    "serverstatus": true,
    "ss": true,
    "control": false,
    "schedule": false,
    "info": false
  },
  "post_initial": true,
  "enable_auto_refresh": true,
  "update_interval_minutes": 5,
  "recreate_messages_on_inactivity": true,
  "inactivity_timeout_minutes": 60
}
```

### Channel Types

**Status Channel** (read-only status display):

```json
{
  "commands": {
    "serverstatus": true,  // Enable /serverstatus command
    "ss": true,           // Enable /ss alias
    "control": false,     // Disable container control
    "schedule": false,    // Disable scheduling
    "info": false        // Disable info command
  }
}
```

**Control Channel** (full control):

```json
{
  "commands": {
    "serverstatus": true,  // Enable status
    "ss": true,           // Enable alias
    "control": true,      // Enable container control (start/stop/restart)
    "schedule": true,     // Enable scheduling
    "info": true         // Enable info command
  }
}
```

### Auto-Refresh Settings

```json
{
  "enable_auto_refresh": true,         // Enable automatic status updates
  "update_interval_minutes": 5,        // Update every 5 minutes
  "recreate_messages_on_inactivity": true,  // Recreate on long inactivity
  "inactivity_timeout_minutes": 60     // Recreate after 60 minutes
}
```

### Working with Channels

```python
from services.config.config_service import get_config_service

config = get_config_service().get_config()

# Get channel permissions
channel_permissions = config.get('channel_permissions', {})

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
```

## Token Encryption

DDC uses **Fernet encryption** with **PBKDF2 key derivation** for Discord bot tokens.

### Encrypting a Token

```python
from services.config.config_service import get_config_service
from werkzeug.security import generate_password_hash

config_service = get_config_service()

# Step 1: Generate password hash (do this once during setup)
password = "my-secure-password"
password_hash = generate_password_hash(password)
print(f"Password hash: {password_hash}")
# Save this hash to web_ui_password_hash in config!

# Step 2: Encrypt Discord bot token
plaintext_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTA.ABC123.xyz789-example"
encrypted_token = config_service.encrypt_token(
    plaintext_token=plaintext_token,
    password_hash=password_hash
)

if encrypted_token:
    print(f"Encrypted token: {encrypted_token[:50]}...")
    # Save this to bot_token in config!
else:
    print("Encryption failed!")
```

### Decrypting a Token

```python
# Decrypt token (happens automatically when loading config)
decrypted_token = config_service.decrypt_token(
    encrypted_token=encrypted_token,
    password_hash=password_hash
)

if decrypted_token:
    print(f"Decrypted token: {decrypted_token[:20]}...")
    assert decrypted_token == plaintext_token
else:
    print("Decryption failed!")
```

### Security Notes

- **Encryption**: Fernet (AES-128 in CBC mode)
- **Key Derivation**: PBKDF2-HMAC-SHA256
- **Iterations**: 260,000 for key derivation
- **Salt**: Fixed salt for token encryption
- **Cache**: Decrypted tokens are cached encrypted in memory

### Automatic Token Decryption

When you call `get_config()`, the bot token is automatically decrypted:

```python
config = config_service.get_config()

# Encrypted token (stored in config file)
encrypted_token = config['bot_token']

# Decrypted token (automatically decrypted for usage)
decrypted_token = config.get('bot_token_decrypted_for_usage')

if decrypted_token:
    print(f"Bot token ready: {decrypted_token[:20]}...")
else:
    print("Token decryption failed!")
```

## Advanced Settings

### Debug Logging

Enable detailed debug logging:

```json
{
  "scheduler_debug_mode": true
}
```

Then reload logging:

```python
from utils.logging_utils import refresh_debug_status

refresh_debug_status()
```

### Session Timeout

Web UI session timeout in seconds:

```json
{
  "session_timeout": 3600  // 1 hour
}
```

### Donation System

Disable donations with a key:

```json
{
  "donation_disable_key": "your-secret-key-here"
}
```

### Docker Settings

Fine-tune Docker daemon interaction:

```json
{
  "docker_socket_path": "/var/run/docker.sock",
  "container_command_cooldown": 5,  // Seconds between commands
  "docker_api_timeout": 30,         // API request timeout
  "max_log_lines": 50              // Max log lines to fetch
}
```

## Saving Configuration

### From Code

```python
from services.config.config_service import get_config_service

config_service = get_config_service()
config = config_service.get_config()

# Modify configuration
config['language'] = 'en'
config['timezone'] = 'America/New_York'

# Save configuration
result = config_service.save_config(config)

if result.success:
    print(f"Config saved: {result.message}")
else:
    print(f"Error: {result.error}")
```

### From Web UI

Use the ConfigurationSaveService:

```python
from services.web.configuration_save_service import (
    get_configuration_save_service,
    ConfigurationSaveRequest
)

save_service = get_configuration_save_service()

# Create save request from form data
save_request = ConfigurationSaveRequest(
    form_data=request.form,
    config_split_enabled=False
)

# Save configuration
result = save_service.save_configuration(save_request)

if result.success:
    print(f"Success: {result.message}")

    if result.critical_settings_changed:
        print("Critical settings changed - caches have been invalidated")
```

## Migration from v1.x

DDC automatically migrates legacy v1.x configs to the new modular structure.

### What Happens During Migration

1. **Legacy files detected** (bot_config.json, docker_config.json, etc.)
2. **Modular structure created** (config/, containers/, channels/)
3. **Data migrated** to new files
4. **Legacy files preserved** (for rollback if needed)

### Manual Migration

To manually migrate:

```python
from services.config.config_migration_service import ConfigMigrationService
from services.config.config_service import get_config_service

config_service = get_config_service()
migration_service = config_service._migration_service

# Migrate legacy config
migration_service.migrate_legacy_v1_config_if_needed(
    load_json_func=config_service._load_json_file,
    save_json_func=config_service._save_json_file,
    extract_bot_config=config_service._validation_service.extract_bot_config,
    extract_docker_config=config_service._validation_service.extract_docker_config,
    extract_web_config=config_service._validation_service.extract_web_config,
    extract_channels_config=config_service._validation_service.extract_channels_config
)
```

## Troubleshooting

### Config Not Loading

```python
from services.exceptions import ConfigLoadError

try:
    config = config_service.get_config()
except ConfigLoadError as e:
    print(f"Error: {e.message}")
    print(f"Error code: {e.error_code}")
    print(f"Details: {e.details}")

    # Use default config
    config = get_default_config()
```

### Cache Issues

```python
from services.exceptions import ConfigCacheError

try:
    config = config_service.get_config()
except ConfigCacheError as e:
    print(f"Cache error: {e.message}")

    # Retry without cache
    config = config_service.get_config(force_reload=True)
```

### Token Decryption Failed

If token decryption fails:

1. Check that `web_ui_password_hash` is set correctly
2. Ensure the encrypted token was encrypted with the same password
3. Try re-encrypting the token
4. Check logs for specific error messages

## See Also

- [SERVICES.md](SERVICES.md) - Service architecture and patterns
- [EXAMPLES.md](EXAMPLES.md) - Complete code examples
- [ERROR_HANDLING.md](ERROR_HANDLING.md) - Exception handling guide
