# Contributing to DDC

Thank you for your interest in contributing to DockerDiscordControl!

## Development Branch Notice

**IMPORTANT**: The main branch is production-only as of v2.0.0 (2025-11-18). All development work happens in the `v2.0` branch.

**To contribute**:
```bash
# Clone the repository
git clone https://github.com/DockerDiscordControl/DockerDiscordControl.git
cd DockerDiscordControl

# Switch to development branch
git checkout origin/v2.0

# Create your feature branch from v2.0
git checkout -b feature/your-feature-name

# Install development dependencies
pip install -r requirements-test.txt
```

The `v2.0` branch contains:
- Full test suite and testing infrastructure
- Code quality tools (.pylintrc, .flake8, mypy.ini)
- CI/CD workflows
- Development documentation

---

## Code Standards

### Python Style

- **PEP 8** compliance
- **Type hints** for all function parameters and return values
- **Google-style docstrings** for all public methods
- **Maximum line length**: 100 characters

### Service Guidelines

When creating or modifying services:

1. **Single Responsibility**: Each service does one thing well
2. **Size Limit**: Keep services under 500 lines
3. **Request/Result Pattern**: Use dataclasses for input/output
4. **Custom Exceptions**: Raise domain-specific exceptions
5. **Logging**: Log all operations with appropriate levels
6. **Thread Safety**: Use locks for shared state
7. **Testing**: Write unit tests for all public methods

### Docstring Format

Use Google-style docstrings:

```python
def my_method(param1: str, param2: int = 0) -> Dict[str, Any]:
    """Short description of the method.

    Longer description explaining what the method does.

    Args:
        param1 (str): Description of param1
        param2 (int, optional): Description of param2. Defaults to 0.

    Returns:
        Dict[str, Any]: Description of return value.

    Raises:
        ConfigServiceError: When configuration is invalid
        ValueError: When param1 is empty

    Example:
        >>> result = my_method("test", param2=5)
        >>> print(result)
    """
    pass
```

### Exception Handling

Use specific exceptions from `services.exceptions`:

```python
from services.exceptions import ConfigServiceError, ConfigLoadError

try:
    config = load_config()
except ConfigLoadError as e:
    logger.error(f"Config load error: {e.message}", exc_info=True)
    raise
```

Always log with `exc_info=True` for errors.

## Testing

**Note**: Testing infrastructure is available in the `v2.0` branch only.

### Running Tests

```bash
# Ensure you're on the v2.0 branch
git checkout origin/v2.0

# Run all tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_config_service.py

# Run with coverage
python -m pytest --cov=services --cov-report=html
```

### Writing Tests

```python
import pytest
from services.config.config_service import get_config_service

class TestConfigService:
    def test_get_config(self):
        config_service = get_config_service()
        config = config_service.get_config()

        assert isinstance(config, dict)
        assert 'language' in config
```

## Pull Requests

1. **Fork** the repository
2. **Switch** to the `v2.0` branch
3. **Create** a feature branch from `v2.0`
4. **Make** your changes
5. **Test** thoroughly (tests available in `v2.0` branch)
6. **Commit** with clear messages
7. **Push** to your fork
8. **Create** a pull request targeting the `v2.0` branch

### Commit Messages

Use clear, descriptive commit messages:

```
🎯 FEATURE: Add container health check support

- Added health_status field to container status
- Implemented health check in docker_utils
- Added tests for health check functionality
```

## Documentation

Update documentation when adding features:

- **SERVICES.md** - For new services
- **CONFIGURATION.md** - For config changes
- **EXAMPLES.md** - For new examples
- **ERROR_HANDLING.md** - For new exceptions

## Questions?

Open an issue on GitHub for questions or suggestions!
