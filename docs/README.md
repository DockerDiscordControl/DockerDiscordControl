# DockerDiscordControl Documentation

Official documentation for DockerDiscordControl v2.0 - Production Release.

## Getting Started

New to DDC? Start here:

1. [Main README](../README.md) - Installation and quick start
2. [CONFIGURATION.md](CONFIGURATION.md) - Configuration guide
3. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues and solutions

## Documentation Index

### User Documentation

| Document | Description |
|----------|-------------|
| [CONFIGURATION.md](CONFIGURATION.md) | Complete configuration guide for Web UI and environment variables |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Solutions for common issues and problems |
| [SECURITY.md](SECURITY.md) | Security best practices and incident response |
| [SUPPORTED_VERSIONS.md](SUPPORTED_VERSIONS.md) | Version support and upgrade instructions |
| [CHANGELOG.md](CHANGELOG.md) | Release history and version changes |

### Platform-Specific Guides

| Document | Description |
|----------|-------------|
| [UNRAID.md](UNRAID.md) | Unraid installation and configuration guide |
| [UNRAID_TROUBLESHOOTING.md](UNRAID_TROUBLESHOOTING.md) | Unraid-specific troubleshooting |

## Quick Reference

### Essential Topics

**First-Time Setup:**
- Default Web UI: `http://your-server:9374`
- Set `DDC_ADMIN_PASSWORD` before starting (recommended)
- Or use temporary credentials `admin` / `setup` and change immediately

**Configuration:**
- Primary method: Web UI at port 9374
- Alternative: Environment variables in docker-compose.yml
- All settings accessible via Web UI

**Common Tasks:**
- Add containers: Web UI → Container Management
- Set permissions: Web UI → Channel Configuration
- View logs: Web UI → Logs or `docker logs ddc`
- Troubleshooting: See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

## Feature Highlights

### Multi-Language Support
- German, French, and English translations
- Dynamic language switching via Web UI
- 100% translation coverage

### Container Management
- Control Docker containers from Discord
- Start, stop, restart actions
- Real-time status updates
- Scheduled tasks

### Mech Evolution System
- 11-stage evolution with animations
- Power decay tracking
- Premium key support
- Visual feedback

### Security Features
- Token encryption (Fernet + PBKDF2)
- Non-root container execution
- Read-only Docker socket mounting
- Strong password hashing (PBKDF2-SHA256)
- Session management

### Performance
- 16x faster Docker status cache
- 7x faster container processing
- Smart queue system
- Optimized async operations

## Documentation Structure

### User-Focused
Production documentation focuses on:
- How to configure and use DDC
- Troubleshooting common issues
- Security best practices
- Platform-specific guides

### Development Documentation
Development documentation is archived in the `v2.0` branch.

## Support

### Getting Help

1. **Check documentation:**
   - [CONFIGURATION.md](CONFIGURATION.md) for setup questions
   - [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues
   - [SECURITY.md](SECURITY.md) for security questions

2. **GitHub Issues:**
   - Search existing issues first
   - Include version, logs, and steps to reproduce
   - Redact sensitive information (tokens, passwords)

3. **Required information for bug reports:**
   ```bash
   # Version
   docker exec ddc python -c "print('v2.0.0')"

   # Logs
   docker logs ddc --tail 100

   # Configuration check
   docker exec ddc ls -la /app/config/
   ```

### Security Issues

For security vulnerabilities:
- Do NOT create public GitHub issues
- Contact project maintainers privately
- See [SECURITY.md](SECURITY.md) for details

## Version Information

**Current Version:** v2.0.0 (Released 2025-11-18)

**Key Changes in v2.0:**
- Production-ready release
- Multi-language support
- Performance improvements
- Security hardening
- Modern Web UI

See [CHANGELOG.md](CHANGELOG.md) for complete release history.

## External Resources

### Related Technologies

- [Discord Developer Portal](https://discord.com/developers/docs) - Discord bot documentation
- [Docker Documentation](https://docs.docker.com/) - Docker reference
- [Flask Documentation](https://flask.palletsprojects.com/) - Web framework docs

### Community

- **GitHub Repository:** https://github.com/DockerDiscordControl/DockerDiscordControl
- **Docker Hub:** https://hub.docker.com/r/dockerdiscordcontrol/dockerdiscordcontrol
- **Issues:** https://github.com/DockerDiscordControl/DockerDiscordControl/issues

## Project Structure

```
DockerDiscordControl/
├── app/                 # Flask Web UI application
├── bot.py              # Discord bot entry point
├── cogs/               # Discord bot commands and features
├── config/             # Configuration storage
├── docs/               # Documentation (you are here)
├── services/           # Business logic services
├── utils/              # Utility functions
├── docker-compose.yml  # Docker deployment configuration
├── Dockerfile          # Container build configuration
└── requirements.txt    # Python dependencies
```

## Contributing

DockerDiscordControl v2.0 is production-ready and stable.

For feature requests or bug reports:
1. Check existing GitHub issues
2. Create detailed issue with reproduction steps
3. Include environment information

Development continues in the `v2.0` branch.

## License

DockerDiscordControl is licensed under the MIT License.
See the LICENSE file in the repository for details.

## Acknowledgments

Built with:
- Python 3.13
- Discord.py
- Docker SDK for Python
- Flask 3.1.1
- Alpine Linux 3.22.1

Thank you to all contributors and users!
