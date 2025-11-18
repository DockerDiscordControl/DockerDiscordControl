# DDC Error Handling Guide

## Overview

DockerDiscordControl uses a structured exception hierarchy for robust error handling and recovery.

## Exception Hierarchy

All DDC exceptions inherit from `DDCBaseException`:

```python
from services.exceptions import DDCBaseException

class DDCBaseException(Exception):
    """Base exception with structured error data."""
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
```

## Exception Categories

### 1. Configuration Exceptions (`ConfigServiceError`)
- **ConfigLoadError**: Configuration loading failures
- **ConfigSaveError**: Configuration saving failures
- **ConfigValidationError**: Configuration validation failures
- **ConfigMigrationError**: Configuration migration failures
- **ConfigCacheError**: Configuration cache operation failures
- **TokenEncryptionError**: Token encryption/decryption failures

### 2. Docker Service Exceptions (`DockerServiceError`)
- **DockerConnectionError**: Docker daemon connection failures
- **DockerClientPoolExhausted**: Connection pool exhausted
- **DockerCommandTimeoutError**: Docker command timeouts
- **ContainerNotFoundError**: Container not found
- **ContainerActionError**: Container action failures (start/stop/restart)
- **ContainerLogError**: Container log fetch failures

### 3. Donation Service Exceptions (`DonationServiceError`)
- **DonationKeyValidationError**: Donation key validation failures
- **DonationAPIError**: External donation API failures
- **DonationDataError**: Donation data processing failures

### 4. Mech Service Exceptions (`MechServiceError`)
- **MechStateError**: Mech state operation failures
- **MechEvolutionError**: Evolution calculation failures
- **MechAnimationError**: Animation generation failures
- **MechPowerDecayError**: Power decay calculation failures

### 5. Web Service Exceptions (`WebServiceError`)
- **AuthenticationError**: Authentication failures
- **AuthorizationError**: Authorization failures
- **SessionError**: Session management failures
- **FormValidationError**: Web form validation failures

## Usage Patterns

### Pattern 1: Basic Exception Handling

```python
from services.exceptions import ConfigServiceError, ConfigLoadError

def load_config():
    try:
        config = _load_config_from_file()
        return config
    except FileNotFoundError as e:
        raise ConfigLoadError(
            "Config file not found",
            error_code="CONFIG_FILE_NOT_FOUND",
            details={'path': str(config_file)}
        )
    except json.JSONDecodeError as e:
        raise ConfigLoadError(
            "Invalid JSON in config file",
            error_code="CONFIG_INVALID_JSON",
            details={'line': e.lineno, 'column': e.colno}
        )
```

### Pattern 2: Error Recovery with Retry

```python
from services.exceptions import ConfigCacheError, is_recoverable_error

def get_config(force_reload: bool = False):
    try:
        if not force_reload:
            cached = cache_service.get_cached_config()
            if cached:
                return cached
    except ConfigCacheError as e:
        logger.warning(f"Cache error: {e.message}")
        # Cache errors are recoverable - retry without cache
        try:
            return get_config(force_reload=True)
        except Exception as retry_error:
            logger.error(f"Retry failed: {retry_error}", exc_info=True)
            raise
```

### Pattern 3: Graceful Degradation

```python
from services.exceptions import ConfigCacheError

def save_config(config):
    try:
        _save_to_file(config)

        # Try to invalidate cache (non-critical)
        try:
            cache_service.invalidate_cache()
        except ConfigCacheError as cache_error:
            logger.warning(f"Cache invalidation failed (non-critical): {cache_error.message}")
            # Continue - save was successful

        return ConfigServiceResult(success=True, message="Config saved")

    except IOError as e:
        raise ConfigSaveError(
            f"Failed to save config: {str(e)}",
            error_code="CONFIG_SAVE_IO_ERROR",
            details={'path': str(config_file)}
        )
```

### Pattern 4: Multiple Exception Types

```python
from services.exceptions import (
    ConfigLoadError, ConfigCacheError,
    TokenEncryptionError
)

def get_config_service(request):
    try:
        config = self.get_config(force_reload=request.force_reload)
        return GetConfigResult(success=True, config=config)

    except ConfigLoadError as e:
        logger.error(f"Config load error: {e.message}", exc_info=True)
        return GetConfigResult(success=False, error_message=e.message)

    except ConfigCacheError as e:
        logger.warning(f"Cache error (non-critical): {e.message}")
        # Retry without cache
        try:
            config = self.get_config(force_reload=True)
            return GetConfigResult(success=True, config=config)
        except Exception as retry_error:
            logger.error(f"Retry failed: {retry_error}", exc_info=True)
            return GetConfigResult(
                success=False,
                error_message=f"Failed after cache error: {str(retry_error)}"
            )

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return GetConfigResult(
            success=False,
            error_message=f"Unexpected error: {str(e)}"
        )
```

## Error Recovery Strategies

### Strategy 1: Retry with Backoff

```python
import time
from services.exceptions import DockerConnectionError, is_recoverable_error

def execute_with_retry(operation, max_retries=3, backoff=1.0):
    """Execute operation with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as e:
            if not is_recoverable_error(e):
                # Not recoverable, raise immediately
                raise

            if attempt == max_retries - 1:
                # Last attempt failed
                raise

            wait_time = backoff * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
```

### Strategy 2: Fallback to Defaults

```python
from services.exceptions import ConfigLoadError

def get_setting(key, default=None):
    """Get setting with fallback to default value."""
    try:
        config = load_config()
        return config.get(key, default)
    except ConfigLoadError as e:
        logger.warning(f"Failed to load config: {e.message}. Using default: {default}")
        return default
```

### Strategy 3: Circuit Breaker Pattern

```python
from services.exceptions import DockerConnectionError
import time

class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'closed'  # closed, open, half-open

    def call(self, operation):
        if self.state == 'open':
            if time.time() - self.last_failure_time > self.timeout:
                self.state = 'half-open'
            else:
                raise DockerConnectionError(
                    "Circuit breaker is OPEN - too many failures",
                    error_code="CIRCUIT_BREAKER_OPEN"
                )

        try:
            result = operation()
            if self.state == 'half-open':
                self.state = 'closed'
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = 'open'

            raise
```

## Helper Functions

### Check if Error is Recoverable

```python
from services.exceptions import is_recoverable_error

if is_recoverable_error(exception):
    # Retry logic
    retry_operation()
else:
    # Not recoverable, raise
    raise
```

### Check if Admin Should Be Alerted

```python
from services.exceptions import should_alert_admin

if should_alert_admin(exception):
    # Send notification to admin
    send_admin_alert(exception)
```

### Get Structured Error Info

```python
from services.exceptions import get_exception_info

error_info = get_exception_info(exception)
# Returns: {'error': 'ConfigLoadError', 'error_code': 'CONFIG_LOAD_FAILED', 'message': '...', 'details': {...}}
```

## Logging Best Practices

### Always use exc_info=True for errors

```python
try:
    risky_operation()
except ConfigServiceError as e:
    logger.error(f"Config error: {e.message}", exc_info=True)
    raise
```

### Use appropriate log levels

```python
# DEBUG: Detailed diagnostic information
logger.debug(f"Loading config from {path}")

# INFO: General informational messages
logger.info("Config loaded successfully")

# WARNING: Warning messages for recoverable issues
logger.warning(f"Cache error (non-critical): {e.message}")

# ERROR: Error messages for failures
logger.error(f"Failed to save config: {e.message}", exc_info=True)
```

## Testing Exception Handling

```python
import pytest
from services.exceptions import ConfigLoadError

def test_config_load_error():
    """Test that ConfigLoadError is raised on file not found."""
    with pytest.raises(ConfigLoadError) as exc_info:
        load_config_from_file('nonexistent.json')

    assert exc_info.value.error_code == 'CONFIG_FILE_NOT_FOUND'
    assert 'nonexistent.json' in exc_info.value.details['path']
```

## Migration Guide

### From Old Code:

```python
# ❌ OLD: Generic exception handling
try:
    config = load_config()
except Exception as e:
    logger.error(f"Error: {e}")
    return None
```

### To New Code:

```python
# ✅ NEW: Specific exception handling with recovery
try:
    config = load_config()
except ConfigLoadError as e:
    logger.error(f"Config load error: {e.message}", exc_info=True)
    # Try fallback or return defaults
    return get_default_config()
except ConfigCacheError as e:
    logger.warning(f"Cache error: {e.message}")
    # Retry without cache
    return load_config(force_reload=True)
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise
```

## Automated Migration Strategy

### Current State

The codebase analysis (via `tools/analyze_exception_handlers.py`) identifies **581 generic Exception handlers** across **98 files** that should be replaced with specific custom exceptions.

### Migration Priority

**Phase 1: Critical Services (Immediate)**
1. `services/config/config_service.py` - 12 handlers
2. `services/docker_service/docker_utils.py` - 25 handlers
3. `services/docker_service/docker_client_pool.py` - 16 handlers
4. `services/donation/unified/service.py` - handlers
5. `services/mech/mech_service.py` - handlers

**Phase 2: High-Traffic Routes (High Priority)**
1. `app/blueprints/main_routes.py` - 35 handlers
2. `app/utils/web_helpers.py` - 18 handlers
3. `services/web/task_management_service.py` - 23 handlers
4. `services/web/configuration_save_service.py` - 16 handlers

**Phase 3: Mech System (Medium Priority)**
1. `services/mech/animation_cache_service.py` - 33 handlers
2. `services/mech/mech_data_store.py` - 15 handlers
3. `services/mech/mech_status_cache_service.py` - 9 handlers

**Phase 4: Scheduling & Utilities (Lower Priority)**
1. `services/scheduling/scheduler.py` - 21 handlers
2. `services/scheduling/scheduler_service.py` - 10 handlers
3. `utils/time_utils.py` - 12 handlers
4. `utils/logging_utils.py` - 11 handlers

### Automated Analysis Tool

Run the analyzer to identify candidates for refactoring:

```bash
# Full analysis with suggestions
python3 tools/analyze_exception_handlers.py --suggest-replacements --top 20

# Detailed analysis with context
python3 tools/analyze_exception_handlers.py --detailed --suggest-replacements
```

### Refactoring Patterns

#### Pattern 1: Simple Replacement

**Before:**
```python
try:
    config = load_config()
except Exception as e:
    logger.error(f"Error loading config: {e}")
    return None
```

**After:**
```python
from services.exceptions import ConfigLoadError

try:
    config = load_config()
except FileNotFoundError as e:
    raise ConfigLoadError(
        "Config file not found",
        error_code="CONFIG_FILE_NOT_FOUND",
        details={'path': str(config_path)}
    )
except json.JSONDecodeError as e:
    raise ConfigLoadError(
        "Invalid JSON format",
        error_code="CONFIG_INVALID_JSON",
        details={'line': e.lineno, 'column': e.colno}
    )
```

#### Pattern 2: Catch Specific Exceptions, Bubble Up Others

**Before:**
```python
try:
    result = docker_operation()
except Exception as e:
    logger.error(f"Docker error: {e}")
    return {"success": False, "error": str(e)}
```

**After:**
```python
from services.exceptions import (
    DockerConnectionError,
    DockerCommandTimeoutError,
    ContainerNotFoundError
)

try:
    result = docker_operation()
except aiodocker.DockerError as e:
    if "connection" in str(e).lower():
        raise DockerConnectionError(
            "Failed to connect to Docker daemon",
            error_code="DOCKER_CONNECTION_FAILED",
            details={'error': str(e)}
        )
    elif "timeout" in str(e).lower():
        raise DockerCommandTimeoutError(
            "Docker command timed out",
            error_code="DOCKER_TIMEOUT",
            details={'error': str(e)}
        )
    else:
        # Unknown Docker error - re-raise as generic DockerServiceError
        raise DockerServiceError(
            f"Docker operation failed: {e}",
            error_code="DOCKER_OPERATION_FAILED",
            details={'error': str(e), 'type': type(e).__name__}
        )
```

#### Pattern 3: Multiple Layers with Recovery

**Before:**
```python
def save_config(config):
    try:
        _save_to_file(config)
        cache.invalidate()
        return True
    except Exception as e:
        logger.error(f"Error: {e}")
        return False
```

**After:**
```python
from services.exceptions import (
    ConfigSaveError,
    ConfigCacheError
)

def save_config(config):
    try:
        _save_to_file(config)
    except IOError as e:
        raise ConfigSaveError(
            f"Failed to write config file: {e}",
            error_code="CONFIG_WRITE_FAILED",
            details={'path': str(config_path), 'error': str(e)}
        )
    except PermissionError as e:
        raise ConfigSaveError(
            "Permission denied writing config file",
            error_code="CONFIG_PERMISSION_DENIED",
            details={'path': str(config_path)}
        )

    # Cache invalidation is non-critical
    try:
        cache.invalidate()
    except ConfigCacheError as e:
        logger.warning(f"Cache invalidation failed (non-critical): {e.message}")
        # Continue - save was successful

    return True
```

#### Pattern 4: Service Layer with Result Objects

**Before:**
```python
def process_donation(request):
    try:
        # Process donation
        result = _process(request)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"success": False, "error": str(e)}
```

**After:**
```python
from services.exceptions import (
    DonationServiceError,
    DonationKeyValidationError,
    DonationAPIError
)
from services.donation.unified.models import DonationResult

def process_donation(request: DonationRequest) -> DonationResult:
    try:
        # Validate donation key
        if not self._validate_key(request.key):
            raise DonationKeyValidationError(
                "Invalid donation key",
                error_code="DONATION_KEY_INVALID",
                details={'key_prefix': request.key[:4]}
            )

        # Call external API
        api_result = self._call_external_api(request)

        # Process result
        new_state = self._update_mech_state(api_result.amount)

        return DonationResult(
            success=True,
            new_state=new_state,
            old_state=old_state
        )

    except DonationKeyValidationError as e:
        logger.warning(f"Donation validation failed: {e.message}")
        return DonationResult(
            success=False,
            error_code=e.error_code,
            error_message=e.message
        )

    except DonationAPIError as e:
        logger.error(f"Donation API error: {e.message}", exc_info=True)
        return DonationResult(
            success=False,
            error_code=e.error_code,
            error_message="External donation service temporarily unavailable"
        )

    except Exception as e:
        logger.error(f"Unexpected error processing donation: {e}", exc_info=True)
        return DonationResult(
            success=False,
            error_code="DONATION_UNEXPECTED_ERROR",
            error_message="An unexpected error occurred"
        )
```

### Exception Selection Guide

| Context | Specific Exception | When to Use |
|---------|-------------------|-------------|
| **Config File Loading** | `ConfigLoadError` | File not found, JSON parse errors |
| **Config File Saving** | `ConfigSaveError` | Write failures, permission errors |
| **Config Validation** | `ConfigValidationError` | Invalid values, missing required fields |
| **Config Migration** | `ConfigMigrationError` | Version migration failures |
| **Config Cache** | `ConfigCacheError` | Cache read/write failures (non-critical) |
| **Token Operations** | `TokenEncryptionError` | Encryption/decryption failures |
| **Docker Connection** | `DockerConnectionError` | Daemon unreachable, socket errors |
| **Docker Timeout** | `DockerCommandTimeoutError` | Operation timeout |
| **Container Not Found** | `ContainerNotFoundError` | Container doesn't exist |
| **Container Actions** | `ContainerActionError` | Start/stop/restart failures |
| **Container Logs** | `ContainerLogError` | Log fetch failures |
| **Pool Exhausted** | `DockerClientPoolExhausted` | No available connections |
| **Donation Validation** | `DonationKeyValidationError` | Invalid donation key |
| **Donation API** | `DonationAPIError` | External API failures |
| **Donation Data** | `DonationDataError` | Data processing errors |
| **Mech State** | `MechStateError` | State load/save failures |
| **Mech Evolution** | `MechEvolutionError` | Evolution calculation errors |
| **Mech Animation** | `MechAnimationError` | Animation generation failures |
| **Mech Power Decay** | `MechPowerDecayError` | Power decay calculation errors |
| **Task Scheduling** | `TaskSchedulingError` | Schedule creation failures |
| **Task Execution** | `TaskExecutionError` | Scheduled task failures |
| **Cron Parsing** | `CronParseError` | Invalid cron expressions |
| **File Storage** | `FileStorageError` | File I/O failures |
| **Data Integrity** | `DataIntegrityError` | Corrupted data detected |
| **Web Auth** | `AuthenticationError` | Login failures |
| **Web Form** | `FormValidationError` | Invalid form data |

### Testing Refactored Code

After refactoring, ensure proper test coverage:

```python
import pytest
from services.exceptions import ConfigLoadError

def test_config_load_file_not_found():
    """Test that ConfigLoadError is raised when file not found."""
    with pytest.raises(ConfigLoadError) as exc_info:
        config_service.load_config('nonexistent.json')

    assert exc_info.value.error_code == 'CONFIG_FILE_NOT_FOUND'
    assert 'nonexistent.json' in str(exc_info.value.details['path'])

def test_config_load_invalid_json():
    """Test that ConfigLoadError is raised for invalid JSON."""
    with pytest.raises(ConfigLoadError) as exc_info:
        config_service.load_config('invalid.json')

    assert exc_info.value.error_code == 'CONFIG_INVALID_JSON'
    assert 'line' in exc_info.value.details
```

### Migration Checklist

For each file being refactored:

- [ ] Run analyzer to identify all generic handlers
- [ ] Review each handler context
- [ ] Identify underlying library exceptions (FileNotFoundError, JSONDecodeError, etc.)
- [ ] Select appropriate custom exception from services/exceptions.py
- [ ] Add structured error_code and details
- [ ] Update logging to include exc_info=True for errors
- [ ] Add recovery logic where appropriate
- [ ] Update or create unit tests for new exception handling
- [ ] Test manually to ensure proper error propagation
- [ ] Commit with descriptive message

### Tracking Progress

**Current Status:**
- Total handlers: 581
- Phase 1 target: ~80 handlers (critical services)
- Phase 2 target: ~100 handlers (high-traffic routes)
- Phase 3 target: ~60 handlers (mech system)
- Phase 4 target: ~50 handlers (utilities)
- Remaining: ~291 handlers (lower priority files)

Run the analyzer regularly to track progress:

```bash
python3 tools/analyze_exception_handlers.py | grep "Total generic handlers"
```

## Summary

- **Use specific exceptions** instead of generic `Exception`
- **Include exc_info=True** in error logs for full stack traces
- **Add error_code and details** for structured error information
- **Implement recovery strategies** where appropriate
- **Use helper functions** for consistent error handling
- **Log at appropriate levels** (DEBUG, INFO, WARNING, ERROR)
- **Test exception handling** with unit tests
- **Follow migration patterns** when refactoring generic handlers
