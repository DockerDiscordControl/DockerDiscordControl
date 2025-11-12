# DDC Documentation

Complete documentation for DockerDiscordControl.

## Documentation Files

| File | Description |
|------|-------------|
| [SERVICES.md](SERVICES.md) | Service architecture and API reference |
| [CONFIGURATION.md](CONFIGURATION.md) | Configuration guide with examples |
| [EXAMPLES.md](EXAMPLES.md) | Practical code examples |
| [ERROR_HANDLING.md](ERROR_HANDLING.md) | Exception handling guide |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |
| [SECURITY.md](SECURITY.md) | Security best practices |

## Quick Links

### For Users

- **Getting Started**: See main [README.md](../README.md)
- **Configuration**: [CONFIGURATION.md](CONFIGURATION.md)
- **Troubleshooting**: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- **Unraid Setup**: [UNRAID.md](UNRAID.md)

### For Developers

- **Service Architecture**: [SERVICES.md](SERVICES.md)
- **Code Examples**: [EXAMPLES.md](EXAMPLES.md)
- **Error Handling**: [ERROR_HANDLING.md](ERROR_HANDLING.md)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)

## Documentation Overview

### SERVICES.md

Complete service architecture documentation:

- Service-oriented architecture overview
- Design patterns (SRP, Request/Result, Singleton, DI)
- Configuration Services (6 services)
- Docker Services
- Donation Services
- Mech Services
- Web Services
- Testing guidelines

**When to read**: Understanding DDC architecture or working with services.

### CONFIGURATION.md

Complete configuration guide:

- Configuration file structure
- Loading and saving configuration
- Container configuration
- Channel configuration
- Token encryption/decryption
- Advanced settings
- Migration from v1.x

**When to read**: Setting up DDC or modifying configuration.

### EXAMPLES.md

Practical code examples:

- Configuration loading
- Token encryption
- Container operations
- Docker async operations
- Error handling
- Testing
- Complete workflow examples

**When to read**: Looking for code examples or learning DDC API.

### ERROR_HANDLING.md

Exception handling guide:

- Custom exception hierarchy (50+ exceptions)
- Domain-specific exceptions
- Error recovery strategies
- Logging best practices
- Migration guide

**When to read**: Implementing error handling or debugging issues.

### CONTRIBUTING.md

Contribution guidelines:

- Code standards (PEP 8, type hints, docstrings)
- Service guidelines (SRP, size limits, patterns)
- Testing requirements
- Pull request process
- Commit message format

**When to read**: Contributing to DDC development.

## Documentation Standards

### Code Documentation

All public APIs must have:

1. **Google-style docstrings**
2. **Type hints** on all parameters
3. **Usage examples**
4. **Exception documentation**

Example:

```python
def get_config(self, force_reload: bool = False) -> Dict[str, Any]:
    """Get unified configuration from all config files.

    Args:
        force_reload (bool): If True, bypass cache and reload from disk.

    Returns:
        Dict[str, Any]: Complete configuration dictionary.

    Raises:
        ConfigLoadError: If configuration files cannot be loaded

    Example:
        >>> config = config_service.get_config()
        >>> print(config['language'])
    """
    pass
```

### Markdown Documentation

Follow these guidelines:

1. **Clear headings** with proper hierarchy
2. **Code blocks** with syntax highlighting
3. **Tables** for structured data
4. **Links** to related documentation
5. **Examples** for all features

## Keeping Documentation Updated

When adding features:

1. **Update relevant .md files**
2. **Add code examples** to EXAMPLES.md
3. **Document exceptions** in ERROR_HANDLING.md
4. **Update service docs** in SERVICES.md
5. **Update config guide** in CONFIGURATION.md

## GitHub Rendering

All documentation is in **Markdown format** and automatically rendered by GitHub.

Navigate to `docs/` in the GitHub repository to browse documentation with:
- Automatic syntax highlighting
- Clickable links
- Formatted tables
- Rendered code blocks

No build step required!

## Additional Resources

### Project Links

- **GitHub**: https://github.com/DockerDiscordControl/DockerDiscordControl
- **Issues**: https://github.com/DockerDiscordControl/DockerDiscordControl/issues
- **Discussions**: https://github.com/DockerDiscordControl/DockerDiscordControl/discussions

### External Documentation

- **Discord.py**: https://discordpy.readthedocs.io/
- **Docker SDK**: https://docker-py.readthedocs.io/
- **Flask**: https://flask.palletsprojects.com/

## Questions?

- **For users**: See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- **For developers**: Open an issue on GitHub
- **For security**: See [SECURITY.md](SECURITY.md)
