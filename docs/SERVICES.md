# DDC Services Documentation

DockerDiscordControl follows a **service-oriented architecture** with clear separation of concerns.
Each service has a single responsibility and uses consistent patterns.

## Service Architecture

```
DockerDiscordControl
│
├── Configuration Services (6 services)
│   ├── ConfigService (main orchestrator)
│   ├── ConfigLoaderService (loading)
│   ├── ConfigMigrationService (migration)
│   ├── ConfigValidationService (validation)
│   ├── ConfigCacheService (caching)
│   └── ConfigFormParserService (web forms)
│
├── Docker Services
│   ├── DockerAsyncQueueService (queue management)
│   └── ContainerService (operations)
│
├── Donation Services
│   ├── DonationService (Ko-fi integration)
│   └── PowerCalculationService (power decay)
│
├── Mech Services
│   ├── MechService (state management)
│   └── MechAnimationService (WebP generation)
│
└── Web Services
    ├── WebUIService (Flask app)
    ├── AuthenticationService (login/sessions)
    └── ConfigurationSaveService (config persistence)
```

## Design Patterns

### 1. Single Responsibility Principle (SRP)

Each service does **one thing well**:

- **ConfigService**: Configuration orchestration only
- **ConfigLoaderService**: Loading configuration only
- **ConfigCacheService**: Caching only
- **ConfigMigrationService**: Migration only

**Benefits**:
- Services stay under 500 lines
- Easy to test
- Easy to maintain
- Clear ownership

### 2. Request/Result Pattern

Services use typed request/result objects:

```python
@dataclass(frozen=True)
class GetConfigRequest:
    force_reload: bool = False

@dataclass(frozen=True)
class GetConfigResult:
    success: bool
    config: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

# Usage
request = GetConfigRequest(force_reload=True)
result = config_service.get_config_service(request)
if result.success:
    config = result.config
```

**Benefits**:
- Type safety
- Clear contract
- Easy to extend
- Testable

### 3. Singleton Pattern

Services are singletons accessed via factory functions:

```python
from services.config.config_service import get_config_service

# Get singleton instance
config_service = get_config_service()

# Multiple calls return same instance
assert config_service is get_config_service()
```

**Benefits**:
- Single source of truth
- Shared state
- Resource efficiency

### 4. Dependency Injection

Services receive dependencies via constructor:

```python
class ConfigLoaderService:
    def __init__(self, config_dir: Path, load_json_func, validation_service):
        self.config_dir = config_dir
        self._load_json_file = load_json_func
        self._validation_service = validation_service
```

**Benefits**:
- Loose coupling
- Easy to test (mock dependencies)
- Flexible composition

## Configuration Services

### ConfigService

**Location**: `services/config/config_service.py`

**Purpose**: Central configuration management - single source of truth for all DDC configuration.

**Key Features**:
- Modular configuration loading (containers, channels, settings)
- Token encryption/decryption with PBKDF2
- Thread-safe operations with locks
- Configuration caching with automatic invalidation
- Legacy v1.x compatibility layer

**Main Methods**:

```python
# Get configuration
config = config_service.get_config()
config = config_service.get_config(force_reload=True)

# Save configuration
result = config_service.save_config(config)

# Token encryption
encrypted = config_service.encrypt_token(plaintext_token, password_hash)
decrypted = config_service.decrypt_token(encrypted_token, password_hash)
```

**Usage Example**:

```python
from services.config.config_service import get_config_service

config_service = get_config_service()
config = config_service.get_config()

print(f"Language: {config['language']}")
print(f"Servers: {len(config['servers'])} containers")
```

See [CONFIGURATION.md](CONFIGURATION.md) for complete config guide.

### ConfigLoaderService

**Location**: `services/config/config_loader_service.py`

**Purpose**: Handles all configuration loading operations.

**Key Features**:
- Real modular structure (individual files per container/channel)
- Virtual modular structure (legacy files)
- Automatic structure detection
- Container filtering (active/inactive)

**Main Methods**:

```python
# Load modular config
config = loader_service.load_modular_config()

# Load containers
servers = loader_service.load_all_containers_from_files()

# Load channels
channel_data = loader_service.load_all_channels_from_files()
```

### ConfigMigrationService

**Location**: `services/config/config_migration_service.py`

**Purpose**: Handles configuration migration between versions.

**Key Features**:
- v1.1.x → v2.0 migration
- Legacy config detection
- Modular structure creation
- Backup support

### ConfigValidationService

**Location**: `services/config/config_validation_service.py`

**Purpose**: Validates configuration data.

**Key Features**:
- Discord token validation
- Config structure validation
- Default value provision

### ConfigCacheService

**Location**: `services/config/config_cache_service.py`

**Purpose**: Manages configuration caching.

**Key Features**:
- File-based cache with modification time checking
- Token caching (encrypted in memory)
- Cache invalidation
- Thread-safe operations

**Usage Example**:

```python
cache_service = ConfigCacheService()

# Get cached config (returns None if expired)
cached = cache_service.get_cached_config('unified', config_dir)

# Set cache
cache_service.set_cached_config('unified', config, config_dir)

# Invalidate all caches
cache_service.invalidate_cache()
```

### ConfigFormParserService

**Location**: `services/config/config_form_parser_service.py`

**Purpose**: Parses web form data into configuration structures.

**Main Methods**:

```python
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
```

## Docker Services

### DockerAsyncQueueService

**Location**: `app/utils/docker_utils.py`

**Purpose**: Modern async queue system for Docker operations.

**Key Features**:
- Max 3 concurrent Docker connections
- Fair request processing (FIFO queue)
- Intelligent timeout management
- Real-time queue statistics

**Usage Example**:

```python
import asyncio
from app.utils.docker_utils import get_container_status_async

async def check_container():
    status = await get_container_status_async('nginx')
    if status:
        print(f"Container: {status['name']}")
        print(f"State: {status['state']}")

asyncio.run(check_container())
```

## Donation Services

### DonationService

**Location**: `services/donation/donation_service.py`

**Purpose**: Ko-fi donation integration and power management.

**Key Features**:
- Ko-fi API integration
- Real-time donation tracking
- Power accumulation ($1 = 1 power)
- Continuous power decay

**Usage Example**:

```python
from services.donation.donation_service import get_donation_service

donation_service = get_donation_service()
power = donation_service.get_current_power()
print(f"Current power: ${power:.2f}")
```

## Mech Services

### MechService

**Location**: `services/mech_service.py`

**Purpose**: Mech evolution and state management.

**Key Features**:
- Dynamic evolution based on power
- State persistence
- Level calculations
- Next evolution requirements

## Web Services

### ConfigurationSaveService

**Location**: `services/web/configuration_save_service.py`

**Purpose**: Complex configuration saving with cache management.

**Key Features**:
- Critical settings change detection
- Cache invalidation
- Translation/timezone cache clearing
- Logging level updates

**Usage Example**:

```python
from services.web.configuration_save_service import (
    get_configuration_save_service,
    ConfigurationSaveRequest
)

save_service = get_configuration_save_service()
save_request = ConfigurationSaveRequest(form_data=request.form)
result = save_service.save_configuration(save_request)

if result.success:
    print(f"Success: {result.message}")
    if result.critical_settings_changed:
        print("Critical settings changed - caches invalidated")
```

## Error Handling

All services use custom exceptions with structured error data.

See [ERROR_HANDLING.md](ERROR_HANDLING.md) for complete exception hierarchy and recovery strategies.

**Quick Example**:

```python
from services.exceptions import ConfigServiceError, ConfigLoadError

try:
    config = config_service.get_config()
except ConfigLoadError as e:
    logger.error(f"Failed to load config: {e.message}", exc_info=True)
    # Use defaults
    config = get_default_config()
```

## Testing Services

### Unit Testing

```python
import pytest
from services.config.config_service import get_config_service

class TestConfigService:
    def test_get_config(self):
        config_service = get_config_service()
        config = config_service.get_config()

        assert isinstance(config, dict)
        assert 'language' in config
        assert 'servers' in config
```

### Integration Testing

```python
@pytest.mark.asyncio
async def test_full_workflow():
    # Load config
    config = get_config_service().get_config()

    # Get container status
    container = config['servers'][0]['container_name']
    status = await get_container_status_async(container)

    assert status is not None
    assert 'state' in status
```

## Service Guidelines

When creating new services:

1. **Single Responsibility**: Each service does one thing well
2. **Typed Interfaces**: Use dataclasses for request/result
3. **Custom Exceptions**: Define domain-specific exceptions
4. **Comprehensive Logging**: Log all operations with appropriate levels
5. **Thread Safety**: Use locks for shared state
6. **Documentation**: Complete docstrings with examples
7. **Testing**: Unit tests for all public methods
8. **Size Limit**: Keep services under 500 lines

## See Also

- [CONFIGURATION.md](CONFIGURATION.md) - Configuration guide with examples
- [EXAMPLES.md](EXAMPLES.md) - Complete code examples
- [ERROR_HANDLING.md](ERROR_HANDLING.md) - Exception handling guide
