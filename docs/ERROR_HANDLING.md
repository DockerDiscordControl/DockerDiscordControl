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

## Summary

- **Use specific exceptions** instead of generic `Exception`
- **Include exc_info=True** in error logs for full stack traces
- **Add error_code and details** for structured error information
- **Implement recovery strategies** where appropriate
- **Use helper functions** for consistent error handling
- **Log at appropriate levels** (DEBUG, INFO, WARNING, ERROR)
- **Test exception handling** with unit tests
